"""
Trainable Graph
"""
from dxl.learn.model import Model
from dxl.learn.session import ThisSession
from dxl.learn.utils import logger
from .trainer.global_step import GlobalStep



class Network(Model):
    """
    A network is a trainable Graph.
    A member maybe added.
    A Network is restricted to has at most one objective/trainer/train_step.
    """

    class KEYS(Model.KEYS):
        class TENSOR(Model.KEYS.TENSOR):
            TRAIN = 'train'
            OBJECTIVE = 'objective'
            ACCURACY = 'accuracy'
            INFERNECES = 'inferences'
            EVALUATE = 'evaluate'
            LABEL = 'label'
            STEP = 'step'

        class GRAPH(Model.KEYS.GRAPH):
            MAIN = 'main'
            TRAINER = 'trainer'
            METRICS = 'metrics'
            SUMMARY_WRITER = 'summary_writer'
            SAVER = 'saver'

    def __init__(self,
                 info='network',
                 *,
                 tensors=None,
                 graphs=None,
                 config=None,
                 trainer=None,
                 metrics=None,
                 summaries=None,
                 saver=None):
        """
        `objectives`: dict of Tensor/tf.tensor or callable. If objectives is a 
        dict of callables, these callables should have current Network
        object as the only input and returns a Tensor/tf.tensor object, note one
        must **NOT** create new variable in this function since it will be called
        outside managed scope.

        """
        KS = self.KEYS.SUBGRAPH
        super().__init__(
            info,
            tensors=tensors,
            graphs=self._parse_input_config(graphs, {
                KS.TRAINER: trainer,
                KS.METRICS: metrics,
                KS.SUMMARY_WRITER: summaries,
                KS.SAVER: saver}
            ),
            config=config
        )

    @classmethod
    def _default_config(cls):
        c = super()._default_config()
        c.update({})
        return c

    def kernel(self, inputs):
        return {}
    
    def post_kernel_in_scope(self, results):
        KT = self.KEYS.TENSOR
        objective = self.apply_metrics(results[KT.INFERNECES])
        self.apply_trainer(objective)

    def apply_metrics(self, infer):
        KT, KG = self.KEYS.TENSOR, self.KEYS.GRAPH
        loss, acc = self.graphs[KG.METRICS](infer)
        self.tensors[KT.OBJECTIVE] = loss
        self.tensors[KT.ACCURACY] = acc
        return loss

    def apply_trainer(self, objective):
        KT, KG = self.KEYS.TENSOR, self.KEYS.GRAPH
        self.graphs[KG.TRAINER](objective)
        self.tensors[KT.TRAIN] = self.graphs[KG.TRAINER].train_step
        self.tensors[KT.STEP] = GlobalStep

    def train(self, name=None, feeds=None):
        """
        `name`: name of trainer (in subgraph)
        """
        if not self.is_made:
            self.make()

        KT = self.KEYS.TENSOR
        trainer = self.tensors[self.KEYS.TENSOR.TRAIN]
        ThisSession.run(trainer, feeds)
        step = ThisSession.run(self.tensors[KT.STEP].increased())

        self.on_end_step(step)

    def inference(self, name=None, feeds=None):
        t = self.tensors[self.KEYS.TENSOR.INFERNECES]
        ThisSession.run(t, feeds)

    def evaluate(self, name=None, feeds=None):
        t = self.tensors[self.KEYS.TENSOR.EVALUATE]
        ThisSession.run(t, feeds)

    def load(self, step=None):
        """
        Restore saved models.
        """
        self.saver.load(step)

    def on_end_step(self, step):
        KG = self.KEYS.GRAPH
        summary_step = self.graphs[KG.SUMMARY_WRITER].summary_step
        if step % summary_step == 0:
            self.graphs[KG.SUMMARY_WRITER].write()

        save_step = self.graphs[KG.SAVER].save_step
        if step % save_step == 0:
            self.graphs[KG.SAVER].save()
            


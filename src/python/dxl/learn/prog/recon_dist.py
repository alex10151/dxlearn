import numpy as np
import click
import tensorflow as tf
from dxl.learn.core import TensorNumpyNDArray, TensorVariable, Tensor, VariableInfo, DistributeGraphInfo, ThisSession, Session, Host, ThisHost
from dxl.learn.core import make_distribute_host, make_distribute_session, Master, Barrier, Server
from dxl.learn.model.recon import ReconStep, ProjectionSplitter, EfficiencyMap
from dxl.learn.model.on_collections import Summation
from dxl.learn.graph.recon import GlobalGraph, LocalGraph
from typing import Iterable
import pdb
import time


NB_WORKERS = 2


def ptensor(t, name=None):
    print("|DEBUG| name: {} | data: {} | run() {} |.".format(name, t.data, t.run()))


def dist_init(job, task):
    cfg = {"master": ["localhost:2221"],
           "worker": ["localhost:2222",
                      "localhost:2223"]}
    make_distribute_host(cfg, job, task, None, 'master', 0)
    master_host = Master.master_host()
    hosts = [Host('worker', i) for i in range(NB_WORKERS)]
    hmi = DistributeGraphInfo(None, None, None, master_host)
    return hosts, hmi


def init_global(hmi):
    root = '/home/hongxwing/Workspace/temptests/recontest/'
    phantom = np.load(root + 'phantom_64.0.npy')
    x = phantom.reshape([phantom.size, 1]).astype(np.float32)
    system_matrix = np.load(root + 'system_matrix_64.npy').astype(np.float32)
    y = np.matmul(system_matrix, x).astype(np.float32)
    x = np.ones(x.shape)
    effmap = np.matmul(system_matrix.T, np.ones(y.shape)).astype(np.float32)
    gg = GlobalGraph(x, y, system_matrix, effmap, hmi)
    return gg


def init_local(global_graph: GlobalGraph, hosts):
    global_graph.split(len(hosts))
    result = [global_graph.copy_to_local(h) for h in hosts]
    return result


def make_recon_local(global_graph, local_graphs):
    for g in local_graphs:
        g.copy_to_global(global_graph)
        g.recon_local()
    global_graph.x_update_by_merge()


def get_my_local_graph(local_graphs: Iterable[LocalGraph]):
    host = ThisHost.host()
    for g in local_graphs:
        if g.graph_info.host == host:
            return g
    raise KeyError("No local graph for {}.{} found".format(
        host.job, host.task_index))


def init_run(master_op, worker_ops,
             global_graph: GlobalGraph,
             local_graphs: Iterable[LocalGraph]):
    if ThisHost.is_master():
        ThisSession.run(master_op)
        ptensor(global_graph.tensor(global_graph.KEYS.TENSOR.X), 'x:global')
    else:
        print('PRE INIT Barrier')
        ptensor(global_graph.tensor(global_graph.KEYS.TENSOR.X),
                'x:global direct fetch')
        ThisSession.run(worker_ops[ThisHost.host().task_index])
        lg = get_my_local_graph(local_graphs)
        TK = lg.KEYS.TENSOR
        ptensor(lg.tensor(TK.X), 'x:local')
        ptensor(lg.tensor(TK.SYSTEM_MATRIX), 'x:local')
    print('INIT DONE. ==============================')


def recon_run(master_op, worker_ops, global_graph, local_graphs):
    if ThisHost.is_master():
        print('PRE RECON')
        ptensor(global_graph.tensor('x'))
        print('START RECON')
        ThisSession.run(master_op)
        print('POST RECON')
        ptensor(global_graph.tensor('x'), 'x:global')
    else:
        print('PRE RECON')
        lg = get_my_local_graph(local_graphs)
        TK = lg.KEYS.TENSOR
        ptensor(lg.tensor(TK.X), 'x:local')
        print('POST RECON')
        ThisSession.run(worker_ops[ThisHost.host().task_index])
        # ptensor(lg.tensor(TK.X_UPDATE), 'x:update')
        ptensor(lg.tensor(TK.X_RESULT), 'x:result')
        ptensor(lg.tensor(TK.X_GLOBAL_BUFFER), 'x:global_buffer')
        # ThisSession.run(ThisHost.host().task_index)


def full_step_run(m_op, w_ops, global_graph, local_graphs, nb_iter=0, verbose=0):
    if verbose > 0:
        print('PRE RECON {}'.format(nb_iter))
        lg = None
        if ThisHost.is_master():
            TK = global_graph.KEYS.TENSOR
            ptensor(global_graph.tensor(TK.X), 'x:global')
        else:
            lg = get_my_local_graph(local_graphs)
            TK = lg.KEYS.TENSOR
            ptensor(lg.tensor(TK.X), 'x:local')
    print('START RECON {}'.format(nb_iter))
    if ThisHost.is_master():
        ThisSession.run(m_op)
    else:
        ThisSession.run(w_ops[ThisHost.host().task_index])
    if verbose > 0:
        print('POST RECON {}'.format(nb_iter))
        if ThisHost.is_master():
            TK = global_graph.KEYS.TENSOR
            ptensor(global_graph.tensor(TK.X), 'x:global')
        else:
            lg = get_my_local_graph(local_graphs)
            TK = lg.KEYS.TENSOR
            ptensor(lg.tensor(TK.X), 'x:local')


def main(job, task):
    hosts, hmi = dist_init(job, task)
    global_graph = init_global(hmi)
    local_graphs = init_local(global_graph, hosts)
    m_op_init, w_ops_init = global_graph.init_op(local_graphs)
    make_recon_local(global_graph, local_graphs)
    m_op_rec, w_ops_rec = global_graph.recon_step(local_graphs, hosts)
    m_op, w_ops = global_graph.merge_step(m_op_rec, w_ops_rec, hosts)
    # global_tensors = {'x': x_t, 'y': y_t, 'sm': sm_t, 'em': e_t}
    # g2l_init, update_global, x_g2l, x_l, y_l, sm_l, em_l = recon_init(
    #     x_t, y_t, sm_t, e_t, hosts, x_init)
    # gop, l_ops = recon_step(update_global, x_g2l, x_l, y_l, sm_l, em_l, hosts)
    # init_op = make_init_op(g2l_init, hosts)
    make_distribute_session()
    tf.summary.FileWriter('./graph', ThisSession.session().graph)
    print('|DEBUG| Make Graph done.')
    
    init_run(m_op_init, w_ops_init, global_graph, local_graphs)
    ptensor(global_graph.tensor(global_graph.KEYS.TENSOR.X))

    # time.sleep(5)
    # recon_run(m_op_rec, w_ops_rec, global_graph, local_graphs)
    for i in range(100):
        full_step_run(m_op, w_ops, global_graph, local_graphs, i)
    ptensor(global_graph.tensor(global_graph.KEYS.TENSOR.X))
    # full_step_run(m_op, w_ops, global_graph, local_graphs, 1)
    # full_step_run(m_op, w_ops, global_graph, local_graphs, 2)
    # if ThisHost.is_master():
    #     ThisSession.run(gop)
    # else:
    #     ThisSession.run(l_ops[ThisHost.host().task_index])
    if ThisHost.is_master():
        res = global_graph.tensor(global_graph.KEYS.TENSOR.X).run()
        np.save('recon.npy', res)
    # print('|DEBUG| JOIN!')
    # Server.join()
    print('DONE!')

    # y_ts, sm_ts = split(y_t, sm_t)
    # make_distribute_session
    # x_init.run()
    # res = ThisSession.run(x_t.data)
    # x_ns = []
    # for i in range(NB_WORKERS):

    #     x_ns.append(recon(x_t, y_ts[i], sm_ts[i],  e_t, i))

    # x_n = sm(x_ns)
    # x_update = x_t.assign(x_n)
    # for i in range(100):
    #     x_update.run()
    # res = x_t.run()
    # print(res)
    # np.save('recon.npy', res)


@click.command()
@click.option('--job', '-j', help = 'Job')
@click.option('--task', '-t', help = 'task', type = int, default = 0)
def cli(job, task):
    main(job, task)


if __name__ == "__main__":
    cli()

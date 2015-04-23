import multiprocessing
import time
import random
import networkx as nx
import subprocess
import uuid
import logging

FORMAT = '%(asctime)s %(message)s'
logging.basicConfig(format=FORMAT,level=logging.INFO)

log = logging.getLogger(__name__)

def print_dag(dag,name):
  dotfilename = '{}.dot'.format(name)
  nx.write_dot(dag,dotfilename)
  with open('{}.png'.format(name),'w') as pngfile:
    subprocess.call(['dot','-Tpng',dotfilename], stdout = pngfile)
  
def mknode(dag,nodename = 'node',taskname = '',taskargs = (),taskkwargs = {}):
  nodenr = len(dag.nodes())
  dag.add_node(nodenr,
    nodenr = nodenr,
    nodeid = str(uuid.uuid1()),
    nodename = nodename,
    taskname = taskname,
    args = taskargs,
    kwargs = taskkwargs
  )
  return dag.node[nodenr]
  
def random_dag(nodes, edges):
    """Generate a random Directed Acyclic Graph (DAG) with a given number of nodes and edges."""
    G = nx.DiGraph()
    for i in range(nodes):
        mknode(G,nodename = 'demo_node_{}'.format(i),
                 taskname = 'hello',
                 taskkwargs = {'workdir':'workdir_{}'.format(i)}
                 )
    while edges > 0:
        a = random.randint(0,nodes-1)
        b=a
        while b==a:
            b = random.randint(0,nodes-1)
        G.add_edge(a,b)
        if nx.is_directed_acyclic_graph(G):
            edges -= 1
        else:
            # we closed a loop!
            G.remove_edge(a,b)
    return G


tasks = {}

def hello(workdir):
  log.info("running job in workdir {}".format(workdir))
  time.sleep(10*random.random())
  
  if random.random() < 0:
    log.error('ERROR! in workdir {}'.format(workdir))
    raise IOError
  log.info("done {}".format(workdir))


tasks['hello'] = hello

def newtask():
  log.info('doing some other task')
  time.sleep(5*random.random())
tasks['newtask'] = newtask


def validate_finished_dag(dag):
  for node in dag:
    nodedict = dag.node[node]
    if 'submitted' in nodedict:
      sanity = all([nodedict['submitted'] > dag.node[x]['ready_by'] for x in dag.predecessors(node)])
      if not sanity:
        return False
  return True

def node_present(nodenr,dag):
  return nodenr in dag.nodes()

def schedule_after_this(parentnr,taskinfo,dag):
  newnode = mknode(dag,nodename = 'dynamic_node',
                     taskname = 'newtask'
                  )
  dag.add_edge(parentnr,newnode['nodenr'])
    
def setup():  
  pool = multiprocessing.Pool(4)
  def submit(func,args = (),kwargs = {}):
    return pool.apply_async(func,args,kwargs)
  return submit

def node_status(dag,node):
  nodedict = dag.node[node]
  submitted = 'result' in nodedict
  ready = nodedict['result'].ready() if submitted else False
  successful = nodedict['result'].successful() if ready else False
  log.debug("node {}: submitted: {}, ready: {}, successful: {}".format(node,submitted,ready,successful))

  if ready and ('ready_by' not in nodedict):
    nodedict.update(ready_by = time.time())

  return submitted and ready and successful

def node_ran_and_failed(dag,node):
  submitted = dag.node[node].has_key('result')
  ready = dag.node[node]['result'].ready() if submitted else False
  successful = dag.node[node]['result'].successful() if ready else False
  log.debug("node {}: submitted: {}, ready: {}, successful: {}".format(node,submitted,ready,successful))

  if (submitted and ready):
    if not successful:
      log.debug('node {}: ran {}, failed {}'.format(node,submitted and ready,successful) )
      return True
  return False

def upstream_ok(dag,node):
  upstream = dag.predecessors(node)
  log.debug("upstream nodes are {}".format(dag.predecessors(node)))
  if not upstream:
    return True
  return all(node_status(dag,x) for x in upstream)

def upstream_failure(dag,node):
  upstream = dag.predecessors(node)
  if not upstream:
    return False

  upstream_status = [node_ran_and_failed(dag,x) or upstream_failure(dag,x) for x in upstream]
  log.debug('upstream status: {}'.format(upstream_status))
  return any(upstream_status)

import IPython

def nodes_left(dag):
  nodes_we_could_run = [node for node in dag.nodes() if not upstream_failure(dag,node)]
  nodes_not_running = [dag.node[node] for node in nodes_we_could_run if not dag.node[node].has_key('result')]
  if nodes_not_running:
    log.info('{} nodes that could be run are left.'.format(len(nodes_not_running)))
    return True
  else:
    log.info('no nodes can be run anymore')
    return False

def rule_applicable(dag,ruleset,ruletoapply):
  rulename, ruleinfo = ruletoapply

  predkwargs = ruleinfo['predicate']['kwargs'].copy()
  predkwargs.update(dag = dag)

  return ruleset[rulename]['predicate'](*ruleinfo['predicate']['args'],**predkwargs)
  

def apply_rule(dag,ruleset,ruletoapply):
  rulename, ruleinfo = ruletoapply
  bodykwargs = ruleinfo['body']['kwargs'].copy()
  bodykwargs.update(dag = dag)
  ruleset[rulename]['body'](*ruleinfo['body']['args'],**bodykwargs)

def main():

  dag = random_dag(3,2)


  ruleset = {}
  ruleset['schedule_after_this'] = {'predicate':node_present,'body':schedule_after_this}


  rules = []
  rules += [['schedule_after_this',{'predicate':{'args':[1,],'kwargs':{} },
                                   'body': {'args':[1,None],'kwargs':{} }
                                   }
            ],
            ['schedule_after_this',{'predicate':{'args':[3,],'kwargs':{} },
                                               'body': {'args':[3,None],'kwargs':{} }
                                               }
                        ]
           ]

  print_dag(dag, 'dag1')

  for node in nx.topological_sort(dag):
    log.info('{} depends on {}'.format(node,dag.predecessors(node)))
    
  submit = setup()

  #while we have nodes that can be submitted
  while nodes_left(dag):
    for node in nx.topological_sort(dag):
      nodedict = dag.node[node]
      log.debug("working on node: {} with dict {}".format(node,nodedict))
      if 'result' in nodedict:
        log.debug("node {} already submitted. continue".format(node))
        continue;
      if upstream_ok(dag,node):
        log.info('submitting node: {}'.format(node))
        result = submit(tasks[nodedict['taskname']],nodedict['args'],nodedict['kwargs'])
        nodedict.update(result = result,submitted = time.time())

      if upstream_failure(dag,node):
        log.warning('not submitting node: {} due to upstream failure'.format(node))

    #iterate rules in reverse so we can safely pop items
    for i,rule in reversed([x for x in enumerate(rules)]):
      if rule_applicable(dag,ruleset,rule):
        log.info('applying a rule!')
        apply_rule(dag,ruleset,rule)
        rules.pop(i)
        
    time.sleep(1)

  #wait for all results to finish
  for node in dag.nodes():
    if 'result' in dag.node[node]:
      dag.node[node]['result'].wait()


  for node in dag.nodes():
    #check node status one last time
    node_status(dag,node)

  log.info('all running jobs are finished.')

  print_dag(dag, 'dag2')

  if not validate_finished_dag(dag):
    log.error('DAG execution not validating')
    raise RuntimeError
  log.info('execution valid.')
if __name__=='__main__':
  main()
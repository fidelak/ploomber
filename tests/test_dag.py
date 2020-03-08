from unittest.mock import Mock
from pathlib import Path

import pytest

from ploomber.dag import DAG
from ploomber.tasks import ShellScript, PythonCallable, SQLDump
from ploomber.products import File
from ploomber.constants import TaskStatus, DAGStatus
from ploomber.exceptions import DAGBuildError


class FailedTask(Exception):
    pass


def touch_root(product):
    Path(str(product)).touch()


def touch(upstream, product):
    Path(str(product)).touch()


def failing(product):
    raise FailedTask('Bad things happened')


# can test this since this uses dag.plot(), which needs dot for plotting
# def test_to_html():
#     def fn1(product):
#         pass

#     def fn2(product):
#         pass

#     dag = DAG()
#     t1 = PythonCallable(fn1, File('file1.txt'), dag)
#     t2 = PythonCallable(fn2, File('file2.txt'), dag)
#     t1 >> t2

#     dag.to_html('a.html')


def test_warn_on_python_missing_docstrings():
    def fn1(product):
        pass

    dag = DAG()
    PythonCallable(fn1, File('file1.txt'), dag, name='fn1')

    with pytest.warns(UserWarning):
        dag.diagnose()


def test_does_not_warn_on_python_docstrings():
    def fn1(product):
        """This is a docstring
        """
        pass

    dag = DAG()
    PythonCallable(fn1, File('file1.txt'), dag, name='fn1')

    with pytest.warns(None) as warn:
        dag.diagnose()

    assert not warn


def test_warn_on_sql_missing_docstrings():
    dag = DAG()

    sql = 'SELECT * FROM table'
    SQLDump(sql, File('file1.txt'), dag, client=Mock(), name='sql')

    with pytest.warns(UserWarning):
        dag.diagnose()


def test_does_not_warn_on_sql_docstrings():
    dag = DAG()

    sql = '/* get data from table */\nSELECT * FROM table'
    SQLDump(sql, File('file1.txt'), dag, client=Mock(), name='sql')

    with pytest.warns(None) as warn:
        dag.diagnose()

    assert not warn


# def test_can_use_null_task(tmp_directory):
#     dag = DAG('dag')

#     Path('a.txt').write_text('hello')

#     ta = Null(File('a.txt'), dag, 'ta')
#     tb = ShellScript('cat {{upstream["ta"]}} > {{product}}', File('b.txt'),
#                      dag, 'tb')

#     ta >> tb

#     dag.build()

#     assert Path('b.txt').read_text() == 'hello'


def test_can_get_upstream_tasks():
    dag = DAG('dag')

    ta = ShellScript('echo "a" > {{product}}', File('a.txt'), dag, 'ta')
    tb = ShellScript('cat {{upstream["ta"]}} > {{product}}',
                     File('b.txt'), dag, 'tb')
    tc = ShellScript('cat {{upstream["tb"]}} > {{product}}',
                     File('c.txt'), dag, 'tc')

    ta >> tb >> tc

    assert set(ta.upstream) == set()
    assert set(tb.upstream) == {'ta'}
    assert set(tc.upstream) == {'tb'}


def test_can_access_sub_dag():
    sub_dag = DAG('sub_dag')

    ta = ShellScript('echo "a" > {{product}}', File('a.txt'), sub_dag, 'ta')
    tb = ShellScript('cat {{upstream["ta"]}} > {{product}}',
                     File('b.txt'), sub_dag, 'tb')
    tc = ShellScript('tcat {{upstream["tb"]}} > {{product}}',
                     File('c.txt'), sub_dag, 'tc')

    ta >> tb >> tc

    dag = DAG('dag')

    fd = Path('d.txt')
    td = ShellScript('touch {{product}}', File(fd), dag, 'td')

    td.set_upstream(sub_dag)

    assert 'sub_dag' in td.upstream


def test_can_access_tasks_inside_dag_using_getitem():
    dag = DAG('dag')
    dag2 = DAG('dag2')

    ta = ShellScript('touch {{product}}', File(Path('a.txt')), dag, 'ta')
    tb = ShellScript('touch {{product}}', File(Path('b.txt')), dag, 'tb')
    tc = ShellScript('touch {{product}}', File(Path('c.txt')), dag, 'tc')

    # td is still discoverable from dag even though it was declared in dag2,
    # since it is a dependency for a task in dag
    td = ShellScript('touch {{product}}', File(Path('c.txt')), dag2, 'td')
    # te is not discoverable since it is not a dependency for any task in dag
    te = ShellScript('touch {{product}}', File(Path('e.txt')), dag2, 'te')

    td >> ta >> tb >> tc >> te

    assert set(dag) == {'ta', 'tb', 'tc', 'td'}


def test_partial_build(tmp_directory):
    dag = DAG('dag')

    ta = ShellScript('echo "hi" >> {{product}}',
                     File(Path('a.txt')), dag, 'ta')
    code = 'cat {{upstream.first}} >> {{product}}'
    tb = ShellScript(code, File(Path('b.txt')), dag, 'tb')
    tc = ShellScript(code, File(Path('c.txt')), dag, 'tc')
    td = ShellScript(code, File(Path('d.txt')), dag, 'td')
    te = ShellScript(code, File(Path('e.txt')), dag, 'te')

    ta >> tb >> tc
    tb >> td >> te

    table = dag.build_partially('tc')

    assert {row['name'] for row in table} == {'ta', 'tb', 'tc'}
    assert all(row['Ran?'] for row in table)


@pytest.mark.parametrize('executor', ['parallel', 'serial'])
def test_dag_task_status_life_cycle(executor, tmp_directory):
    """
    Check dag and task status along calls to DAG.render and DAG.build.
    Although DAG and Task status are automatically updated and propagated
    downstream upon calls to render and build, we have to parametrize this
    over executors since the object that gets updated might not be the same
    one that we declared here (this happens when a task runs in a different
    process), hence, it is the executor's responsibility to notify tasks
    on sucess/fail scenarios so downstream tasks are updated correctly
    """
    dag = DAG(executor=executor)
    t1 = PythonCallable(touch_root, File('ok'), dag, name='t1')
    t2 = PythonCallable(failing, File('a_file'), dag, name='t2')
    t3 = PythonCallable(touch, File('another_file'), dag, name='t3')
    t4 = PythonCallable(touch, File('yet_another_file'), dag, name='t4')
    t5 = PythonCallable(touch_root, File('file'), dag, name='t5')
    t2 >> t3 >> t4

    assert dag._exec_status == DAGStatus.WaitingRender
    assert {TaskStatus.WaitingRender} == set([t.exec_status
                                              for t in dag.values()])

    dag.render()

    assert dag._exec_status == DAGStatus.WaitingExecution
    assert t1.exec_status == TaskStatus.WaitingExecution
    assert t2.exec_status == TaskStatus.WaitingExecution
    assert t3.exec_status == TaskStatus.WaitingUpstream
    assert t4.exec_status == TaskStatus.WaitingUpstream
    assert t5.exec_status == TaskStatus.WaitingExecution

    try:
        dag.build()
    except DAGBuildError:
        pass

    assert dag._exec_status == DAGStatus.Errored
    assert t1.exec_status == TaskStatus.Executed
    assert t2.exec_status == TaskStatus.Errored
    assert t3.exec_status == TaskStatus.Aborted
    assert t4.exec_status == TaskStatus.Aborted
    assert t5.exec_status == TaskStatus.Executed

    dag.render()

    assert dag._exec_status == DAGStatus.Errored
    assert t1.exec_status == TaskStatus.Executed
    assert t2.exec_status == TaskStatus.Errored
    assert t3.exec_status == TaskStatus.Aborted
    assert t4.exec_status == TaskStatus.Aborted
    assert t5.exec_status == TaskStatus.Executed

    # TODO: add test when trying to Execute dag with task status
    # other than WaitingExecution anf WaitingUpstream

    dag.build()

    assert dag._exec_status == DAGStatus.Errored
    assert t1.exec_status == TaskStatus.Executed
    assert t2.exec_status == TaskStatus.Errored
    assert t3.exec_status == TaskStatus.Aborted
    assert t4.exec_status == TaskStatus.Aborted
    assert t5.exec_status == TaskStatus.Executed

    # render again to check status reset
    dag.render(force=True)

    assert dag._exec_status == DAGStatus.WaitingExecution
    assert t1.exec_status == TaskStatus.WaitingExecution
    assert t2.exec_status == TaskStatus.WaitingExecution
    assert t3.exec_status == TaskStatus.WaitingUpstream
    assert t4.exec_status == TaskStatus.WaitingUpstream
    assert t5.exec_status == TaskStatus.WaitingExecution


@pytest.mark.parametrize('executor', ['parallel', 'serial'])
def test_executor_keeps_running_until_no_more_tasks_can_run(executor,
                                                            tmp_directory):
    dag = DAG(executor=executor)
    t_fail = PythonCallable(failing, File('t_fail'), dag, name='t_fail')
    t_fail_downstream = PythonCallable(failing, File('t_fail_downstream'),
                                       dag, name='t_fail_downstream')
    t_touch_aborted = PythonCallable(touch_root, File('t_touch_aborted'),
                                     dag, name='t_touch_aborted')

    t_fail >> t_fail_downstream >> t_touch_aborted

    PythonCallable(touch_root, File('t_ok'), dag, name='t_ok')

    try:
        dag.build(force=True)
    except DAGBuildError:
        pass

    assert not Path('t_fail').exists()
    assert not Path('t_fail_downstream').exists()
    assert Path('t_ok').exists()


def test_warns_on_rendered_dag():
    dag = DAG()
    PythonCallable(touch_root, File('ok'), dag, name='t1')
    dag.render()

    with pytest.warns(UserWarning) as record:
        dag.render()

    expected_msg = ('DAG("No name") has already been rendered, this call has '
                    'no effect, to force rendering again, pass force=True')

    assert len(record) == 1
    assert record[0].message.args[0] == expected_msg


def test_warns_on_built_dag(tmp_directory):
    dag = DAG()
    PythonCallable(touch_root, File('ok'), dag, name='t1')
    dag.build()

    with pytest.warns(UserWarning) as record:
        dag.build()

    expected_msg = ('DAG("No name") has been built already, to force pass '
                    'force=True')

    assert len(record) == 1
    assert record[0].message.args[0] == expected_msg
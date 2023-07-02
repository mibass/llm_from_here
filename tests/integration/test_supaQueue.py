import os
import pytest
from llm_from_here.supaQueue import SupaQueue
import dotenv
dotenv.load_dotenv()

SUPASET_URL = os.environ.get('SUPASET_URL')
SUPASET_KEY = os.environ.get('SUPASET_KEY')

@pytest.fixture
def queue(request):
    queue_name = "test_queue"
    queue = SupaQueue(queue_name)
    queue.clear()
    def fin():
        queue.clear()
    request.addfinalizer(fin)
    return queue

def test_enqueue(queue):
    queue.enqueue(['value1', 'value2'])
    values = queue.peek(2)
    assert values == ['value1', 'value2']

def test_dequeue(queue):
    queue.enqueue(['value1', 'value2', 'value3'])
    values = queue.dequeue(2)
    assert values == ['value1', 'value2']
    values = queue.peek(3)
    assert values == ['value3']

def test_peek(queue):
    queue.enqueue(['value1', 'value2', 'value3'])
    values = queue.peek(2)
    assert values == ['value1', 'value2']

def test_cleanup_incomplete_sessions(queue):
    queue.enqueue(['value1', 'value2', 'value3'])
    queue.dequeue(2)
    queue._cleanup_incomplete_sessions()
    values = queue.peek(3)
    assert values == ['value1', 'value2', 'value3']

def test_length(queue):
    queue.enqueue(['value1', 'value2', 'value3'])
    assert queue.length() == 3
    queue.dequeue()
    assert queue.length() == 2

def test_finalize(queue):
    queue.enqueue(['value1', 'value2', 'value3'])
    queue.dequeue(2)
    assert queue.length() == 1
    queue.finalize()
    queue._cleanup_incomplete_sessions()
    assert queue.length() == 1
    queue.dequeue()
    queue.finalize()
    queue._cleanup_incomplete_sessions()
    assert queue.length() == 0

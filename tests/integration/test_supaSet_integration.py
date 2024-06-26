import os
import pytest
from llm_from_here.supaSet import SupaSet
import dotenv
dotenv.load_dotenv()

SUPASET_URL = os.environ.get('SUPASET_URL')
SUPASET_KEY = os.environ.get('SUPASET_KEY')

@pytest.fixture
def setup_supaset(request):
    sset_name = "test_set"
    sset = SupaSet(sset_name)
    sset.clear()
    def fin():
        sset.clear()
    request.addfinalizer(fin)
    return sset

def test_add_and_remove_values(setup_supaset):
    supaset = setup_supaset
    value1 = "test_value"
    value2 = "test_value2"

    # Test add functionality
    assert supaset.add(value1) == True, "Should return True when adding a new value"
    assert value1 in supaset, "Added value should be in the supaset"
    assert supaset.add(value1) == False, "Should return False when adding an existing value"
    assert value1 in supaset, "Added value should be in the supaset"

    #add another value
    assert supaset.add(value2) == True, "Should return True when adding a new value"
    assert value2 in supaset, "Added value should be in the supaset"
    assert supaset.add(value2) == False, "Should return False when adding an existing value"
    assert value2 in supaset, "Added value should be in the supaset"
    assert value1 in supaset, "Added value should still be in the supaset"

    # Test remove functionality
    supaset.remove(value1)
    assert value1 not in supaset, "Removed value should not be in the supaset"
    assert value2 in supaset, "Other value should still be in the supaset"
    supaset.remove(value2)
    assert value2 not in supaset, "Removed value should not be in the supaset"

def test_autoexpire(setup_supaset):
    supaset = setup_supaset
    value = "test_value"

    # Test add functionality
    assert supaset.add(value) == True, "Should return True when adding a new value"
    assert value in supaset, "Added value should be in the supaset"

    # Test autoexpire functionality
    supaset.autoexpire(-1)
    assert value not in supaset, "Value should be removed from supaset after autoexpire"

def test_cleanup_incomplete_sessions(setup_supaset):
    supaset = setup_supaset
    value = "test_value"

    # Test add functionality
    assert supaset.add(value) == True, "Should return True when adding a new value"
    assert value in supaset, "Added value should be in the supaset"

    # Test cleanup functionality, value should remain because cleanup only applies to other session ids
    supaset._cleanup_incomplete_sessions()
    assert value in supaset, "Value should be removed from supaset after cleanup incomplete sessions"

def test_complete_session(setup_supaset):
    supaset = setup_supaset
    value = "test_value"

    # Test add functionality
    assert supaset.add(value) == True, "Should return True when adding a new value"
    assert value in supaset, "Added value should be in the supaset"

    # Test complete session functionality
    supaset.complete_session()
    assert value in supaset, "Value should be removed from supaset after complete session"

    # Test cleanup functionality for complete session
    supaset._cleanup_incomplete_sessions()
    assert value in supaset, "Value should in supaset after cleanup incomplete sessions"

def test_shared_session_id():
    # Create multiple instances of SupaSet
    supaset1 = SupaSet('set1')
    supaset2 = SupaSet('set2')
    supaset3 = SupaSet('set3')

    # Assert that all instances share the same session_id
    assert supaset1.session_id == supaset2.session_id == supaset3.session_id

    # Optionally, you can also check that other attributes are distinct
    assert supaset1.set_name != supaset2.set_name
    assert supaset2.set_name != supaset3.set_name

def test_shared_session_incomplete_cleaup():
    # Create multiple instances of SupaSet
    supaset1 = SupaSet('set1')
    supaset2 = SupaSet('set2')
    supaset3 = SupaSet('set3')

    # Add a value to each supaset
    supaset1.add('value1')
    supaset2.add('value2')
    supaset3.add('value3')

    # Assert that all instances share the same session_id
    assert supaset1.session_id == supaset2.session_id == supaset3.session_id

    # If I cleanup set 1, it should not affect set 2 or 3 since they share the same session_id
    supaset1._cleanup_incomplete_sessions()

    # Assert that all instances share the same session_id
    assert 'value1' in supaset1
    assert 'value2' in supaset2
    assert 'value3' in supaset3

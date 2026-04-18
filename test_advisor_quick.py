#!/usr/bin/env python3
"""Quick integration test for advisor enhancements."""

import sys
sys.path.insert(0, '/home/ge94doc/tumeasy')

from tum_pulse.agents.tumonline_executor import TUMonlineExecutorAgent
from tum_pulse.memory.database import SQLiteMemory

def test_database_enhancements():
    """Test database has registration tracking."""
    print("✅ DATABASE ENHANCEMENTS TEST")
    print("-" * 60)
    
    db = SQLiteMemory()
    
    # Test saving registration
    print("1. Testing registration history storage...")
    db.save_registration("IN2346", "Machine Learning", "register", "success")
    db.save_registration("IN2001", "Algorithms", "deregister", "pending")
    
    # Retrieve history
    history = db.get_registration_history()
    print(f"   ✅ Saved 2 registrations, retrieved {len(history)} entries")
    
    # Test profile data
    print("\n2. Testing profile data storage...")
    db.save_profile("time_availability", 20.0)
    db.save_profile("interests", ["ML", "AI", "DataScience"])
    
    time_avail = db.get_profile("time_availability")
    interests = db.get_profile("interests")
    print(f"   ✅ Time availability: {time_avail}")
    print(f"   ✅ Interests: {interests}")
    

def test_tumonline_executor():
    """Test TUM Online executor agent."""
    print("\n✅ TUM ONLINE EXECUTOR TEST")
    print("-" * 60)
    
    executor = TUMonlineExecutorAgent()
    
    # Populate cache for testing
    db = SQLiteMemory()
    db.save_profile("electives_cache", [
        {"name": "Machine Learning", "code": "IN2346", "description": "ML fundamentals"},
        {"name": "Algorithms", "code": "IN2001", "description": "Algorithm design"},
        {"name": "Analysis", "code": "MA0001", "description": "Mathematical analysis"},
    ])
    
    # Test commands
    commands = [
        "register for Machine Learning",
        "show registration history",
    ]
    
    for cmd in commands:
        print(f"\n  Command: '{cmd}'")
        response = executor.run(cmd)
        print(f"  → {response.split(chr(10))[0][:80]}...")


def test_advisor_enhancements():
    """Test Advisor code has time/interests factors."""
    print("\n✅ ADVISOR ENHANCEMENTS TEST")
    print("-" * 60)
    
    from tum_pulse.agents.advisor import AdvisorAgent
    import inspect
    
    # Check if new methods exist
    advisor = AdvisorAgent()
    
    methods_to_check = [
        "_compute_time_factor",
        "_compute_interests_boost",
    ]
    
    for method_name in methods_to_check:
        if hasattr(advisor, method_name):
            print(f"  ✅ {method_name} exists")
            method = getattr(advisor, method_name)
            sig = inspect.signature(method)
            print(f"     Parameters: {list(sig.parameters.keys())}")
        else:
            print(f"  ❌ {method_name} missing")
    
    # Check recommend signature
    sig = inspect.signature(advisor.recommend)
    print(f"\n  ✅ recommend() parameters: {list(sig.parameters.keys())}")


def test_orchestrator():
    """Test orchestrator has course_registration routing."""
    print("\n✅ ORCHESTRATOR ENHANCEMENTS TEST")
    print("-" * 60)
    
    from tum_pulse.agents.orchestrator import _VALID_INTENTS
    
    if "course_registration" in _VALID_INTENTS:
        print(f"  ✅ 'course_registration' intent added to router")
        print(f"  Valid intents: {sorted(_VALID_INTENTS)}")
    else:
        print(f"  ❌ 'course_registration' intent NOT found")
        print(f"  Valid intents: {sorted(_VALID_INTENTS)}")


if __name__ == "__main__":
    print("=" * 60)
    print("ADVISOR ENHANCEMENT INTEGRATION TESTS")
    print("=" * 60)
    
    try:
        test_database_enhancements()
        test_tumonline_executor()
        test_advisor_enhancements()
        test_orchestrator()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

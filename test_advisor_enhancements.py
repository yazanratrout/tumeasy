#!/usr/bin/env python3
"""Test script for enhanced Advisor agent with time availability and interests."""

import sys
sys.path.insert(0, '/home/ge94doc/tumeasy')

from tum_pulse.agents.advisor import AdvisorAgent
from tum_pulse.agents.tumonline_executor import TUMonlineExecutorAgent
from tum_pulse.memory.database import SQLiteMemory

def test_advisor_with_time_and_interests():
    """Test Advisor with time availability and interests."""
    print("=" * 70)
    print("TEST: Enhanced Advisor with Time Availability & Interests")
    print("=" * 70)
    
    db = SQLiteMemory()
    advisor = AdvisorAgent()
    
    # Setup test data
    test_profile = {
        "courses": ["Analysis 1", "Linear Algebra", "Programming"],
        "grades": {
            "Analysis 1": 1.7,
            "Linear Algebra": 1.3,
            "Programming": 2.5,
        },
        "time_availability": 15.0,  # 15 hours/week
        "interests": ["Machine Learning", "Data Science"],
        "selected_courses": ["Machine Learning", "AI"],
        "upcoming_deadlines": [
            {"title": "Analysis homework", "deadline_date": "2026-04-25"},
            {"title": "Project submission", "deadline_date": "2026-04-30"},
        ],
    }
    
    print("\n✅ Test Profile:")
    print(f"  Courses: {test_profile['courses']}")
    print(f"  Grades: {test_profile['grades']}")
    print(f"  Time available: {test_profile['time_availability']} hours/week")
    print(f"  Interests: {test_profile['interests']}")
    print(f"  Upcoming deadlines: {len(test_profile['upcoming_deadlines'])} items")
    
    try:
        recommendations = advisor.recommend(test_profile)
        print(f"\n✅ Got {len(recommendations)} recommendations:")
        for i, rec in enumerate(recommendations, 1):
            el = rec["elective"]
            print(f"\n  {i}. {el['name']}")
            print(f"     Code: {el['module_id']}")
            print(f"     Direction: {el['direction']}")
            print(f"     Difficulty: {el['difficulty']}")
            print(f"     Score: {rec['score']}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


def test_tumonline_executor():
    """Test TUM Online executor for registration."""
    print("\n" + "=" * 70)
    print("TEST: TUM Online Executor (Registration)")
    print("=" * 70)
    
    executor = TUMonlineExecutorAgent()
    
    # Test registration workflow
    test_cases = [
        "register for Machine Learning",
        "deregister from Analysis",
        "show my registration history",
    ]
    
    for task in test_cases:
        print(f"\n✅ Task: '{task}'")
        try:
            response = executor.run(task)
            print(f"   Response:\n{response}\n")
        except Exception as e:
            print(f"   ❌ Error: {e}\n")


def test_advisor_context():
    """Test Advisor run method with enhanced context."""
    print("\n" + "=" * 70)
    print("TEST: Advisor run() with Enhanced Context")
    print("=" * 70)
    
    db = SQLiteMemory()
    advisor = AdvisorAgent()
    
    # Save test profile to database
    db.save_profile("courses", ["Analysis 1", "Linear Algebra", "Programming", "Discrete Math"])
    db.save_profile("grades", {
        "Analysis 1": 1.7,
        "Linear Algebra": 1.3,
        "Programming": 2.5,
    })
    db.save_profile("time_availability", 20.0)
    db.save_profile("interests", ["Machine Learning", "Algorithms"])
    db.save_profile("selected_recommendation_courses", ["Machine Learning"])
    
    print("\n✅ Saved test profile to database")
    print("   - 4 courses")
    print("   - Grades with weak subject (Programming: 2.5)")
    print("   - 20 hours/week available")
    print("   - Interests: Machine Learning, Algorithms")
    print("   - Selected for recommendations: Machine Learning")
    
    try:
        response = advisor.run("What courses should I take?")
        print(f"\n✅ Advisor Response (first 500 chars):")
        print(f"   {response[:500]}...")
        
        if "time" in response.lower() or "hour" in response.lower():
            print("\n✅ Time availability mentioned in response ✓")
        else:
            print("\n⚠️  Time availability not explicitly mentioned")
        
        if "machine learning" in response.lower() or "algorithm" in response.lower():
            print("✅ Interests considered in response ✓")
        else:
            print("⚠️  Interests not explicitly mentioned")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_advisor_with_time_and_interests()
    test_tumonline_executor()
    test_advisor_context()
    print("\n" + "=" * 70)
    print("✅ All tests completed!")
    print("=" * 70)

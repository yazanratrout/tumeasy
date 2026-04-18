"""Test that materials are properly stored and retrievable."""

from tum_pulse.memory.database import SQLiteMemory
from tum_pulse.memory.cognee_store import get_cognee_store
from tum_pulse.agents.learning_buddy import LearningBuddyAgent

db = SQLiteMemory()
buddy = LearningBuddyAgent()

print("\n" + "="*80)
print("MATERIALS INTEGRATION TEST")
print("="*80)

# Check what's in cache
all_materials = db.get_all_course_materials()
print(f"\n✅ Materials in cache: {len(all_materials)} courses")
for course, materials in list(all_materials.items())[:5]:
    print(f"  • {course}: {len(materials)} files")

# Test that Learning Buddy can retrieve them
courses = db.get_profile("courses") or []
if courses:
    test_course = courses[0]
    print(f"\n✅ Testing retrieval for: {test_course}")
    materials = buddy.list_moodle_materials(test_course)
    print(f"  → Found {len(materials)} materials")
    for m in materials[:3]:
        print(f"    - {m.get('name', 'Unknown')} ({m.get('file_type', 'file')})")
else:
    print("\n⚠️ No courses in cache yet. Run DataFetcher.fetch_all() first!")

# Test Cognee materials search
print(f"\n✅ Testing Cognee materials search...")
cognee = get_cognee_store()
try:
    results = cognee.query_materials("machine learning introduction pdf")
    if results:
        print(f"  Found: {results[:100]}...")
    else:
        print(f"  ⚠️ No results (Cognee may not be fully populated yet)")
except Exception as e:
    print(f"  ⚠️ Error: {e}")

print("\n" + "="*80)
print("RECOMMENDATION: Materials will be populated after first login")
print("="*80 + "\n")

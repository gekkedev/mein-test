"""
Validator for questions.json
Checks that all questions have exactly 4 non-empty answers.
"""
import json
import sys
from pathlib import Path


def validate_questions(json_path: Path) -> bool:
    """Validate that all questions have exactly 4 non-empty answers."""
    try:
        with open(json_path, encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ Error: File not found: {json_path}")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON: {e}")
        return False

    questions = data.get('questions', [])
    if not questions:
        print("❌ Error: No questions found in JSON")
        return False

    print(f"📊 Validating {len(questions)} questions...")
    
    issues = []
    
    # Check answer counts
    for q in questions:
        answer_count = len(q.get('answers', []))
        if answer_count != 4:
            issues.append({
                'type': 'wrong_count',
                'id': q['id'],
                'display': q['display_number'],
                'count': answer_count
            })
    
    # Check for empty answers
    for q in questions:
        for i, ans in enumerate(q.get('answers', [])):
            if not ans.get('text', '').strip():
                issues.append({
                    'type': 'empty_answer',
                    'id': q['id'],
                    'display': q['display_number'],
                    'answer_index': i
                })
    
    # Report results
    if not issues:
        print("✅ All questions validated successfully!")
        print(f"   • {len(questions)} questions")
        print(f"   • {len(questions) * 4} total answers")
        print(f"   • All questions have exactly 4 non-empty answers")
        return True
    
    # Report issues
    print(f"\n⚠️  Found {len(issues)} validation issues:\n")
    
    wrong_count = [i for i in issues if i['type'] == 'wrong_count']
    empty_answers = [i for i in issues if i['type'] == 'empty_answer']
    
    if wrong_count:
        print(f"❌ {len(wrong_count)} questions with wrong answer count:")
        for issue in wrong_count[:10]:  # Show first 10
            print(f"   • Question {issue['display']} (ID {issue['id']}): {issue['count']} answers (expected 4)")
        if len(wrong_count) > 10:
            print(f"   ... and {len(wrong_count) - 10} more")
    
    if empty_answers:
        print(f"\n❌ {len(empty_answers)} empty answers:")
        for issue in empty_answers[:10]:  # Show first 10
            print(f"   • Question {issue['display']} (ID {issue['id']}), answer {issue['answer_index']}: empty text")
        if len(empty_answers) > 10:
            print(f"   ... and {len(empty_answers) - 10} more")
    
    return False


if __name__ == "__main__":
    json_path = Path("data/questions.json")
    
    # Allow passing custom path as argument
    if len(sys.argv) > 1:
        json_path = Path(sys.argv[1])
    
    success = validate_questions(json_path)
    sys.exit(0 if success else 1)


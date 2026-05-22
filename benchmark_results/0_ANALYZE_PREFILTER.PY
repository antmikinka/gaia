import json
import sys

sys.path.append(r"C:\Users\antmi\gaia-visualizations")

from src.gaia.agents.email.tools.triage_heuristics import classify_category_heuristic

jsonl_path = r"C:\Users\antmi\gaia-visualizations\stratified_1000.jsonl"

print(f"Analyzing: {jsonl_path}\n")

confident_false = []
confident_true = []

with open(jsonl_path, encoding="utf-8") as f:
    for line in f:
        email = json.loads(line)
        
        subject = email.get("subject", "")
        sender = email.get("sender", "")
        
        result = classify_category_heuristic(subject, sender, [])
        
        record = {
            "id": email["id"],
            "sender": sender,
            "subject": subject,
            "heuristic_category": result.category,
            "heuristic_confident": result.confident,
            "dataset_category": email.get("category")
        }
        
        if result.confident:
            confident_true.append(record)
        else:
            confident_false.append(record)

print(f"Total emails: {len(confident_true) + len(confident_false)}")
print(f"confident=True  (heuristic pre-filtered): {len(confident_true)}")
print(f"confident=False (would go to LLM):       {len(confident_false)}")
print(f"Percentage that would reach LLM: {len(confident_false) / (len(confident_true) + len(confident_false)) * 100:.1f}%")

# Optional: Save the confident=false ones
with open("stratified_confident_false.json", "w", encoding="utf-8") as f:
    json.dump(confident_false, f, indent=2)

print("\nSaved confident=false emails to: stratified_confident_false.json")
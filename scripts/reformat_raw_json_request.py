import json

f = "/Users/noah/REPOS/job-search-engine/raw_request_example.json"

with open(f, 'r') as file:
    data = json.load(file)

with open(f, 'w') as file:
    json.dump(data, file, indent=3)
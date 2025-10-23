import os
import requests
from pathlib import Path
import json


class DevOpsDataCollector:
    def __init__(self, output_dir="vector_store_data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
    
    # function for collecting the docs within the k8s website local os does git clone for the docs themselves 
    # places them in docs_path and for loop appends them in documents list

    def collect_k8s_docs(self):
        """Clone and process k8s docs"""
        os.system("git clone --depth 1 https://github.com/kubernetes/website k8s_docs")

        docs_path = Path("k8s_docs/content/en/docs")
        documents = []
        

        # for loop for globbing each md file in the docs within the k8s site 
        # seperating them in a dictionary for source file content and type and appends it to the list 

        for md_file in docs_path.rglob("*.md"):
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
                documents.append({
                    "source" : "kubernetes_docs",
                    "file" : str(md_file),
                    "content" : content,
                    "type" : "documentation"
                })
        return documents
    
    # Function for collecting the CVEs related to kubernetes using the NVD url which gest it in json and parse thenm to be placed in the list and organized with params dictionary 
    def collect_cves(self, product="kubernetes", max_results=1000):
        """Fetch CVEs from NVD"""
        base_url = "https://services.nvd.nist.gov/rest/json/cves/2.0"

        cves = []

        start_index = 0

        while start_index < max_results:
            params = {
                "keywordSearch": product,
                "resultsPerPage": 100,
                "startIndex": start_index,
            }

            response = requests.get(base_url, params=params)
            data = response.json()

            for item in data.get('vulnerabilities', []):
                cve = item['cve']
                cves.append({
                    "source" : "nvd",
                    "cve_id" : cve['id']
                    "description" : cve['descriptions'][0]['valve'],
                    "severity" : cve.get('metrics',{}),
                    "type" : "cve"
                })

        start_index += 100
        time.sleep(100)

        return cves
    
    def collect_stackoverflow(self, tag="kubernetes", max_questions=500):
        """Fetch Stack Overflow Q&A"""
        base_url = "https://api.stackexchange.com/2.3/questions"
        
        questions = []
        page = 1
        
        while len(questions) < max_questions:
            params = {
                "page": page,
                "pagesize": 100,
                "order": "desc",
                "sort": "votes",
                "tagged": tag,
                "site": "stackoverflow",
                "filter": "withbody"  # Includes question body
            }
            
            response = requests.get(base_url, params=params)
            data = response.json()
            
            for q in data.get('items', []):
                # Fetch accepted answer
                answer_url = f"https://api.stackexchange.com/2.3/questions/{q['question_id']}/answers"
                answer_params = {
                    "site": "stackoverflow",
                    "filter": "withbody",
                    "sort": "votes"
                }
                answer_resp = requests.get(answer_url, params=answer_params)
                answers = answer_resp.json().get('items', [])
                
                if answers:
                    questions.append({
                        "source": "stackoverflow",
                        "question": q['title'],
                        "question_body": q.get('body', ''),
                        "answer": answers[0].get('body', ''),
                        "votes": q['score'],
                        "type": "qa"
                    })
            
            page += 1
            time.sleep(0.1)  # Rate limiting
            
            if not data.get('has_more'):
                break
        
        return questions
    
    def save_dataset(self, data, filename):
        """Save collected data"""
        output_path = self.output_dir / filename
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print(f"Saved {len(data)} items to {output_path}")

# Usage
collector = DevOpsDataCollector()

# Collect all data
k8s_docs = collector.collect_k8s_docs()
collector.save_dataset(k8s_docs, "k8s_docs.json")

cves = collector.collect_cves("kubernetes")
collector.save_dataset(cves, "k8s_cves.json")

docker_cves = collector.collect_cves("docker")
collector.save_dataset(docker_cves, "docker_cves.json")

stackoverflow_k8s = collector.collect_stackoverflow("kubernetes")
collector.save_dataset(stackoverflow_k8s, "stackoverflow_k8s.json")




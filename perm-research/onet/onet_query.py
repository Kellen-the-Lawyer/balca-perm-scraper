"""
onet_query.py
-------------
Given a job description (and optional minimum requirements),
returns the top 10 matching SOC codes ranked by similarity.

Usage:
    python3 onet_query.py

Activate your venv first:
    source /Users/Dad/Documents/GitHub/balca-perm-scraper/venv/bin/activate
"""

import psycopg2
from sentence_transformers import SentenceTransformer

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

DB_CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "dbname":   "casebase",
    "user":     "Dad",
    "password": "",
}

MODEL_NAME = "all-MiniLM-L6-v2"
TOP_K      = 10


# ─────────────────────────────────────────────
# QUERY FUNCTION
# ─────────────────────────────────────────────

def find_soc_codes(job_description: str, min_requirements: str = "", top_k: int = TOP_K):
    """
    Encodes the job description + requirements and returns the
    top_k most similar occupations from onet_occupations.

    Returns a list of dicts:
        [{ "rank", "onetsoc_code", "title", "similarity", "description" }, ...]
    """
    # Combine job description and requirements into one query text
    query_text = job_description.strip()
    if min_requirements.strip():
        query_text += "\nMinimum Requirements: " + min_requirements.strip()

    # Encode the query
    model = SentenceTransformer(MODEL_NAME)
    query_embedding = model.encode(query_text, convert_to_numpy=True).tolist()

    # Search pgvector
    sql = """
        SELECT
            onetsoc_code,
            title,
            description,
            1 - (embedding <=> %s::vector) AS similarity
        FROM onet_occupations
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """

    conn = psycopg2.connect(**DB_CONFIG)
    with conn.cursor() as cur:
        cur.execute(sql, (query_embedding, query_embedding, top_k))
        rows = cur.fetchall()
    conn.close()

    results = []
    for rank, (code, title, description, similarity) in enumerate(rows, start=1):
        results.append({
            "rank":        rank,
            "onetsoc_code": code,
            "title":       title,
            "similarity":  round(float(similarity), 4),
            "description": description,
        })

    return results


def print_results(results):
    print(f"\n{'Rank':<5} {'SOC Code':<13} {'Similarity':<12} Title")
    print("-" * 75)
    for r in results:
        print(f"{r['rank']:<5} {r['onetsoc_code']:<13} {r['similarity']:<12} {r['title']}")
    print()
    print("Top match description:")
    print(f"  {results[0]['description']}\n")


# ─────────────────────────────────────────────
# TEST CASES
# ─────────────────────────────────────────────

# A few realistic immigration/PERM job descriptions to test with
TEST_JOBS = [
    {
        "label": "Software Engineer",
        "description": """
            Design, develop, and maintain scalable backend services and APIs.
            Collaborate with cross-functional teams to define and implement new features.
            Write clean, well-tested code in Python and Java. Participate in code reviews
            and contribute to architectural decisions. Debug and resolve production issues.
        """,
        "requirements": "Bachelor's degree in Computer Science or related field. 3 years of experience.",
    },
    {
        "label": "HR Manager",
        "description": """
            Oversee all human resources functions including recruitment, onboarding,
            performance management, and employee relations. Develop and implement HR
            policies and procedures. Partner with leadership to align HR strategy with
            business objectives. Manage benefits administration and compensation programs.
        """,
        "requirements": "Bachelor's degree in Human Resources or Business. 5 years HR experience.",
    },
    {
        "label": "Financial Analyst",
        "description": """
            Prepare financial models, forecasts, and variance analyses to support
            business planning. Analyze financial statements and market trends.
            Present findings and recommendations to senior management.
            Support budgeting and long-range planning processes.
        """,
        "requirements": "Bachelor's degree in Finance or Accounting. CFA preferred.",
    },
]


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("\n=== O*NET SOC Code Matcher ===")

    for job in TEST_JOBS:
        print(f"\n{'='*75}")
        print(f"JOB: {job['label']}")
        print(f"{'='*75}")
        results = find_soc_codes(job["description"], job["requirements"])
        print_results(results)

    # Interactive mode — paste your own job description
    print("\n" + "="*75)
    print("INTERACTIVE MODE — paste a job description (type END on a new line to finish):")
    print("="*75)
    lines = []
    while True:
        line = input()
        if line.strip().upper() == "END":
            break
        lines.append(line)

    if lines:
        user_jd = "\n".join(lines)
        req = input("\nMinimum requirements (press Enter to skip): ")
        results = find_soc_codes(user_jd, req)
        print_results(results)


if __name__ == "__main__":
    main()

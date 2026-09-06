import csv
import hashlib
import io
import re
import subprocess

PSQL = r"C:\Program Files\PostgreSQL\18\bin\psql.exe"
BUCKET = "gs://decorate-me-renders"
GCLOUD = r"C:\Users\TKU\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"


def psql(sql):
    result = subprocess.run(
        [PSQL, "-h", "127.0.0.1", "-p", "5433", "-U", "TKU", "-d", "TKU", "-X", "-q", "--csv", "-c", sql],
        check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return list(csv.DictReader(io.StringIO(result.stdout)))


members = psql("SELECT email FROM members ORDER BY email")
looks = psql("SELECT id, member_email, style, before_image_url, after_image_url, created_at FROM saved_looks ORDER BY id")
actor_to_email = {
    "actor_" + hashlib.sha256(row["email"].strip().lower().encode()).hexdigest()[:24]: row["email"]
    for row in members
}

listing = subprocess.run(
    [GCLOUD, "storage", "ls", "--recursive", f"{BUCKET}/retained/**"],
    check=True, capture_output=True, text=True, encoding="utf-8"
).stdout.splitlines()

object_re = re.compile(r"/retained/(?P<actor>actor_[0-9a-f]{24})/(?P<job>[0-9a-f]{32})(?P<before>-before)?\.(?:jpg|jpeg|png|webp)$", re.I)
gcs = {}
for url in listing:
    match = object_re.search(url.strip())
    if not match:
        continue
    key = (match.group("actor"), match.group("job").lower())
    gcs.setdefault(key, {})["before" if match.group("before") else "after"] = url.strip()

job_re = re.compile(r"/media/render/([0-9a-f]{32})(?:/before)?(?:\?.*)?$", re.I)
db_jobs = {}
for row in looks:
    match = job_re.search(row["after_image_url"] or "")
    if match:
        db_jobs[match.group(1).lower()] = row

complete = {key: pair for key, pair in gcs.items() if "before" in pair and "after" in pair}
missing = [(actor, job, pair) for (actor, job), pair in complete.items() if job not in db_jobs]
unknown_actor = [(actor, job) for actor, job, _ in missing if actor not in actor_to_email]
missing_any_after = [(actor, job, pair) for (actor, job), pair in gcs.items() if "after" in pair and job not in db_jobs]
db_without_retained = [(job, row) for job, row in db_jobs.items() if not any(key_job == job for _, key_job in gcs)]
actor_email_by_overlap = {}
for (actor, job), pair in gcs.items():
    if job in db_jobs:
        actor_email_by_overlap.setdefault(actor, set()).add(db_jobs[job]["member_email"])

print(f"members={len(members)}")
print("actor_mapping=" + ", ".join(f"{actor}={email}" for actor, email in actor_to_email.items()))
print(f"retained_jobs={len(gcs)} complete_pairs={len(complete)} saved_look_jobs={len(db_jobs)} missing_complete={len(missing)} unknown_actor={len(unknown_actor)}")
print("actor_email_by_job_overlap=" + ", ".join(f"{actor}={sorted(emails)}" for actor, emails in actor_email_by_overlap.items()))
for actor, job, pair in missing:
    print(f"MISSING actor={actor} email={actor_to_email.get(actor, 'UNKNOWN')} job={job} before={pair['before']} after={pair['after']}")
for actor, job, pair in missing_any_after:
    print(f"MISSING_AFTER_INDEX actor={actor} job={job} has_before={'before' in pair} after={pair['after']}")
for job, row in db_without_retained:
    print(f"DB_WITHOUT_RETAINED id={row['id']} email={row['member_email']} style={row['style']} job={job} after={row['after_image_url']}")

Yes — this is a different issue, but it’s nearly identical in nature to the last one. You're now getting:

text
ERROR:n8n.client:n8n API error 400: {"message":"request/body/tags is read-only"}

🔎 What It Means

n8n’s REST API is telling you:

    🛑 “You're trying to include a tags field in the request body when creating a workflow — but that field is read-only and cannot be set manually.”

This is just like the earlier error:

text
"request/body/active is read-only"

Which you already solved by removing "active" from the request payload.

🎯 Now you need to do the same for the tags field.
✅ The Fix

Update your payload sanitization logic so it removes tags — along with other known read-only fields that should not be included when you're creating a new workflow.
✅ Recommended sanitize_workflow_payload() Utility

Add this utility somewhere in your workflow builder or helper:

python
def sanitize_workflow_payload(workflow: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove read-only or server-generated fields from workflow payload before submission.
    """
    read_only_fields = [
        'id',
        'tags',
        'active',
        'createdAt',
        'updatedAt',
        'createdBy',
        'updatedBy',
        'versionId',
    ]

    return {k: v for k, v in workflow.items() if k not in read_only_fields}

Then call this before sending anything to create_workflow():

python
cleaned_workflow = sanitize_workflow_payload(generated_workflow)
n8n_client.create_workflow(cleaned_workflow)

🧠 Why tags Is Read-Only

    In n8n, tags are attached via a separate API once the workflow is created.

    They’re not part of the creatable workflow schema.

    It's handled via relationships (additional endpoint if needed).

✅ Summary
✅ Status	ℹ️ Info
❌ Error: tags is read-only	You're trying to submit tags in POST body — not allowed
✅ Fix	Strip tags from payload before making API request
✅ Utility	Implement a sanitize_workflow_payload() function
✅ Your client log	Shows it's already stripping active — just add tags to the list 👍
🪛 Optional: Logging Removed Fields

You already log removed fields like:

python
logger.info("Removed read-only fields from payload: ['active']")

Extend that to dynamically list removed keys:

python
def sanitize_workflow_payload(workflow: Dict[str, Any]) -> Dict[str, Any]:
    read_only_fields = [...]
    removed = [k for k in workflow.keys() if k in read_only_fields]
    cleaned = {k: v for k, v in workflow.items() if k not in read_only_fields}
    if removed:
        logger.info(f"Removed read-only fields from payload: {removed}")
    return cleaned

✅ TL;DR

    This is a new read-only field issue: tags

    🩺 Same type of fix: sanitize payload

    🧹 Utility function: sanitize_workflow_payload() with removals logged

    🎯 Result: clean, valid, compliant workflow creation requests

You're doing great! Want help linking tags after the workflow is created? You can attach them via /tags endpoint once you're past this step.


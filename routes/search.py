# search.py

from flask import Blueprint, request, redirect, url_for, render_template
import pandas as pd
import json
from markupsafe import Markup

from services import (
    retrieve_relevant_documents,
    generate_response,
    extract_key_terms_and_clarify
)
from config import Config

search_bp = Blueprint("search", __name__, url_prefix="/search")

# 1) Load your CT study metadata
data = pd.read_csv(Config.DATA_CSV, encoding="ISO-8859-1")

# Extract diagnostic tasks for canonical GPT mapping
diagnostic_tasks = (
    data["Diagnostic Task"].dropna()
    .astype(str)
    .str.strip()
    .unique()
    .tolist()
)

# 2) Load your CT keyword list once
with open(Config.KEY_TERMS_FILE, "r") as f:
    terms_dict = json.load(f)
CT_TERMS = [
    syn.lower()
    for syn_list in terms_dict.values()
    for syn in syn_list
]

@search_bp.route("", methods=["GET", "POST"])
def search():
    # ── Handle Sankey‑diagram DOI clicks ─────────────────────────────
    doi_list = request.args.getlist("doi")
    if doi_list:
        subset = data[data["DOI Link"].isin(doi_list)]
        if subset.empty:
            return render_template(
                "search.html",
                no_dois=True, irrelevant=False,
                no_results=False, sankey_refs=None,
                active_tab="home"
            )
        icon_url = url_for("static", filename="link-16.png")
        refs_html = ""
        for i, doi in enumerate(doi_list):
            citation = subset[subset["DOI Link"] == doi].iloc[0]["Citation"]
            refs_html += (
                f"{i+1}. {citation} "
                f"<a href='{doi}' target='_blank'>"
                f"<img src='{icon_url}' style='width:16px;vertical-align:middle'></a><br>"
            )
        return render_template(
            "search.html",
            no_dois=False, irrelevant=False,
            no_results=False,
            sankey_refs=Markup(refs_html),
            active_tab="home"
        )

    # ── Only accept POST for normal searches ─────────────────────────
    if request.method != "POST":
        return redirect(url_for("home.home"))

    original_query = request.form.get("query", "").strip()
    if not original_query:
        return redirect(url_for("home.home"))

    lower_q = original_query.lower()

    # ── Shortcut: direct DOI input ──────────────────────────────────
    if original_query.startswith("https://doi.org/"):
        clinical_field, key_terms, clarified_query, diagnostic_task = "bypass", "doi", original_query, None
    else:
        # 3) GPT‐based extraction + clarification with canonical diagnostic task
        clinical_field, key_terms, clarified_query, diagnostic_task = extract_key_terms_and_clarify(original_query, diagnostic_tasks)
        clarified_query = clarified_query.strip().lstrip("*").strip()

        # 4) Off‑topic / irrelevance check *with local rescue*
        found_local = (
            any(term in lower_q for term in CT_TERMS)
            or any(term in (key_terms or "").lower() for term in CT_TERMS)
            or any(term in (clarified_query or "").lower() for term in CT_TERMS)
        )

        # If any field is 'error_extracting' (including Diagnostic Task), always show irrelevant page and do NOT run search
        if (
            "error_extracting" in (clinical_field or "").lower()
            or "error_extracting" in (key_terms or "").lower()
            or "error_extracting" in (clarified_query or "").lower()
            or "error_extracting" in (diagnostic_task or "").lower()
            or clarified_query.lower().startswith("could you provide more information")
        ):
            return render_template(
                "search.html",
                no_dois=False, irrelevant=True,
                no_results=False, sankey_refs=None,
                active_tab="home"
            )

        # Canonical Diagnostic Task match: return those studies directly
        if diagnostic_task and diagnostic_task != "Other":
            mask_task = data["Diagnostic Task"].astype(str).str.strip().str.lower() == diagnostic_task.lower()
            subset = data[mask_task]
            if not subset.empty:
                icon_url = url_for("static", filename="link-16.png")
                refs_html = ""
                for i, (_, row) in enumerate(subset.iterrows()):
                    citation = row["Citation"]
                    doi = row["DOI Link"]
                    refs_html += (
                        f"{i+1}. {citation} "
                        f"<a href='{doi}' target='_blank'>"
                        f"<img src='{icon_url}' style='width:16px;vertical-align:middle'></a><br>"
                    )
                return render_template(
                    "search.html",
                    no_dois=False, irrelevant=False,
                    no_results=False,
                    sankey_refs=Markup(refs_html),
                    clarified_query=original_query,
                    response=None, protocol=None, formatted_refs=None,
                    active_tab="home"
                )
            # If no studies for this task, proceed to fallback below

        # Fallback to semantic search if "Other" or no match
        if found_local:
            clarified_query = original_query

    # ── 5) Pull top‐3 PCCT studies from your pool (semantic search fallback) ──
    docs, found, _ = retrieve_relevant_documents(clarified_query, diagnostic_tasks)
    docs = docs[:3]

    # ── 6) CT‑related but zero matches → “no_results” ───────────────
    if not found:
        return render_template(
            "search.html",
            no_dois=False, irrelevant=False,
            no_results=True, sankey_refs=None,
            active_tab="home"
        )

    # ── 7) Matches found → generate GPT response & protocol ────────
    response, formatted_refs, protocol = generate_response(clarified_query, docs)
    return render_template(
        "search.html",
        no_dois=False, irrelevant=False,
        no_results=False, sankey_refs=None,
        clarified_query=original_query,
        response=response,
        protocol=protocol,
        formatted_refs=Markup(formatted_refs),
        active_tab="home"
    )

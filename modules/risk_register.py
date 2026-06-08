"""Vendor risk register — dashboard queries and exports."""
import io

import pandas as pd

from database.db import session_scope
from database.models import AssessmentHistory, Tenant, Vendor, VendorAssessment
from modules.fair_calculator import TIER_COLORS


def load_register(
    tenant_id: int | None = None,
    risk_tiers: list[str] | None = None,
    contract_statuses: list[str] | None = None,
    certified_only: bool = False,
    latest_only: bool = False,
) -> pd.DataFrame:
    """Return the filtered vendor risk register as a DataFrame."""
    with session_scope() as session:
        query = (
            session.query(VendorAssessment, Vendor, Tenant)
            .join(Vendor, VendorAssessment.vendor_id == Vendor.id)
            .join(Tenant, Vendor.tenant_id == Tenant.id)
        )
        if tenant_id:
            query = query.filter(Tenant.id == tenant_id)
        if risk_tiers:
            query = query.filter(VendorAssessment.risk_tier.in_(risk_tiers))
        if contract_statuses:
            query = query.filter(Vendor.contract_status.in_(contract_statuses))
        rows = query.order_by(VendorAssessment.updated_at.desc()).all()

    if latest_only:
        # Keep only the newest assessment (highest id) per vendor
        newest: dict[int, tuple] = {}
        for row in rows:
            assessment, vendor, _tenant = row
            if vendor.id not in newest or assessment.id > newest[vendor.id][0].id:
                newest[vendor.id] = row
        rows = [r for r in rows if newest[r[1].id] is r]

    records = []
    for assessment, vendor, tenant in rows:
        if certified_only and not assessment.certifications_found:
            continue
        records.append(
            {
                "Assessment ID": assessment.id,
                "Vendor": vendor.name,
                "Tenant": tenant.name,
                "Category": vendor.category,
                "Contract Status": vendor.contract_status,
                "Risk Tier": assessment.risk_tier or "—",
                "ALE P50 ($)": assessment.ale_p50,
                "ALE P90 ($)": assessment.ale_p90,
                "Certifications": assessment.certifications_found or "—",
                "Trust Posture": assessment.public_trust_posture or "—",
                "Status": assessment.status,
                "Updated": assessment.updated_at,
            }
        )
    return pd.DataFrame(records)


def load_trend(vendor_id: int) -> pd.DataFrame:
    """Return assessment history (risk over time) for one vendor."""
    with session_scope() as session:
        rows = (
            session.query(AssessmentHistory)
            .filter(AssessmentHistory.vendor_id == vendor_id)
            .order_by(AssessmentHistory.snapshot_date)
            .all()
        )
    return pd.DataFrame(
        [
            {
                "Date": r.snapshot_date,
                "ALE P50 ($)": r.ale_p50,
                "Risk Tier": r.risk_tier,
            }
            for r in rows
        ]
    )


def list_vendors(tenant_id: int | None = None):
    with session_scope() as session:
        query = session.query(Vendor)
        if tenant_id:
            query = query.filter(Vendor.tenant_id == tenant_id)
        return query.order_by(Vendor.name).all()


def export_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def export_xlsx(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Risk Register")
    return buf.getvalue()


def tier_color(tier: str) -> str:
    return TIER_COLORS.get(tier, "#95a5a6")

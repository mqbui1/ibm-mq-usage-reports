import pandas as pd


def export_excel(totals_df: pd.DataFrame, output_path: str, title: str, period_label: str):
    sheet_name = period_label[:31]  # Excel sheet name limit
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        totals_df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=1)
        worksheet = writer.sheets[sheet_name]
        worksheet["A1"] = f"{title} — {period_label}"

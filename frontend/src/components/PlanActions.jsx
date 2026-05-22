import React from 'react';
import { downloadPlan, openPlanPrint } from '../api/client';

export default function PlanActions({ projectId, planId, planTitle }) {
  if (!projectId || !planId) return null;
  return (
    <div className="moofasa-plan-actions">
      <button
        className="btn"
        onClick={() => downloadPlan(projectId, planId, planTitle)}
        title="Save this plan as a markdown file"
      >
        Save .md
      </button>
      <button
        className="btn"
        onClick={() => openPlanPrint(projectId, planId)}
        title="Open a print-styled page — use ⌘P to save as PDF"
      >
        Print as PDF
      </button>
    </div>
  );
}

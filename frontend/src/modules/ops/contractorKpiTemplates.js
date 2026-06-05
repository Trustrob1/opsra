/**
 * frontend/src/modules/ops/contractorKpiTemplates.js
 * CPM-1A — KPI Template Library
 *
 * Client-side only — no API call. Pre-defined KPI sets per contractor category.
 * Loaded in ContractorCreateModal Step 3 via "Load Template" dropdown.
 * All target values are defaults — manager should adjust per specific contract.
 */

export const KPI_TEMPLATES = [
  {
    id: 'digital_marketing',
    label: 'Digital Marketing Agency',
    kpis: [
      {
        key: 'leads_generated',
        label: 'Monthly Qualified Leads',
        kpi_type: 'leads_generated',
        target_value: 50,
        target_label: '50 leads/month',
        weight_pct: 40,
      },
      {
        key: 'conversion_rate',
        label: 'Lead-to-Appointment Rate',
        kpi_type: 'conversion_rate',
        target_value: 20,
        target_label: '20%',
        weight_pct: 30,
      },
      {
        key: 'response_time',
        label: 'Lead Response Time',
        kpi_type: 'response_time',
        target_value: 2,
        target_label: 'Within 2 hours',
        weight_pct: 15,
      },
      {
        key: 'monthly_report',
        label: 'Monthly Report Delivered',
        kpi_type: 'manual',
        target_value: null,
        target_label: 'Delivered',
        weight_pct: 15,
      },
    ],
  },
  {
    id: 'sales_contractor',
    label: 'Sales / Business Development',
    kpis: [
      {
        key: 'outbound_calls',
        label: 'Outbound Calls Made',
        kpi_type: 'leads_generated',
        target_value: 100,
        target_label: '100 calls/month',
        weight_pct: 30,
      },
      {
        key: 'demos_booked',
        label: 'Demos / Meetings Booked',
        kpi_type: 'leads_generated',
        target_value: 20,
        target_label: '20/month',
        weight_pct: 35,
      },
      {
        key: 'conversion_rate',
        label: 'Demo-to-Close Rate',
        kpi_type: 'conversion_rate',
        target_value: 25,
        target_label: '25%',
        weight_pct: 35,
      },
    ],
  },
  {
    id: 'customer_success',
    label: 'Customer Success / Retention',
    kpis: [
      {
        key: 'churn_rate',
        label: 'Monthly Churn Rate',
        kpi_type: 'conversion_rate',
        target_value: 5,
        target_label: 'Below 5%',
        weight_pct: 40,
      },
      {
        key: 'response_time',
        label: 'Ticket Response Time',
        kpi_type: 'response_time',
        target_value: 4,
        target_label: 'Within 4 hours',
        weight_pct: 30,
      },
      {
        key: 'nps_score',
        label: 'NPS Score',
        kpi_type: 'manual',
        target_value: null,
        target_label: '8+ average',
        weight_pct: 30,
      },
    ],
  },
  {
    id: 'content_creator',
    label: 'Content / Creative Agency',
    kpis: [
      {
        key: 'content_pieces',
        label: 'Content Pieces Delivered',
        kpi_type: 'leads_generated',
        target_value: 12,
        target_label: '12/month',
        weight_pct: 40,
      },
      {
        key: 'engagement_rate',
        label: 'Avg Engagement Rate',
        kpi_type: 'conversion_rate',
        target_value: 3,
        target_label: '3%+',
        weight_pct: 35,
      },
      {
        key: 'approval_turnaround',
        label: 'Content Approval Turnaround',
        kpi_type: 'response_time',
        target_value: 48,
        target_label: 'Within 48 hours',
        weight_pct: 25,
      },
    ],
  },
  {
    id: 'ops_manager',
    label: 'Sales Lead / Manager',
    kpis: [
      {
        key: 'team_revenue_vs_target',
        label: 'Team Revenue vs Target',
        kpi_type: 'conversion_rate',
        target_value: 100,
        target_label: '100% of monthly target',
        weight_pct: 25,
      },
      {
        key: 'team_conversion_rate',
        label: 'Team Conversion Rate',
        kpi_type: 'conversion_rate',
        target_value: 20,
        target_label: '20%',
        weight_pct: 20,
      },
      {
        key: 'pipeline_value',
        label: 'Pipeline Value',
        kpi_type: 'manual',
        target_value: null,
        target_label: 'Monthly pipeline target',
        weight_pct: 15,
      },
      {
        key: 'rep_activity_compliance',
        label: 'Rep Activity Compliance',
        kpi_type: 'conversion_rate',
        target_value: 90,
        target_label: '90% of reps logging daily',
        weight_pct: 15,
      },
      {
        key: 'lead_distribution_rate',
        label: 'Lead Distribution Rate',
        kpi_type: 'leads_generated',
        target_value: 20,
        target_label: '20 leads/rep/month',
        weight_pct: 10,
      },
      {
        key: 'time_to_close',
        label: 'Time to Close',
        kpi_type: 'response_time',
        target_value: 14,
        target_label: 'Within 14 days',
        weight_pct: 10,
      },
      {
        key: 'win_loss_ratio',
        label: 'Win / Loss Ratio',
        kpi_type: 'conversion_rate',
        target_value: 60,
        target_label: '60% win rate',
        weight_pct: 5,
      },
    ],
  },
  {
    id: 'it_support',
    label: 'IT / Technical Support',
    kpis: [
      {
        key: 'tickets_resolved',
        label: 'Tickets Resolved',
        kpi_type: 'leads_generated',
        target_value: 50,
        target_label: '50/month',
        weight_pct: 30,
      },
      {
        key: 'resolution_time',
        label: 'Avg Resolution Time',
        kpi_type: 'response_time',
        target_value: 24,
        target_label: 'Within 24 hours',
        weight_pct: 40,
      },
      {
        key: 'system_uptime',
        label: 'System Uptime',
        kpi_type: 'manual',
        target_value: null,
        target_label: '99.5%+',
        weight_pct: 30,
      },
    ],
  },
]

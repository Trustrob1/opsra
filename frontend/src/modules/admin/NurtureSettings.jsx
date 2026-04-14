// frontend/src/modules/admin/NurtureSettings.jsx
// M01-10a — Lead Nurture Engine admin configuration panel
// Admin can: toggle nurture on/off, set thresholds, build the sequence.

import { useEffect, useState } from "react";
import { getNurtureConfig, updateNurtureConfig } from "../../services/admin.service";

const CONTENT_TYPES = [
  { value: "educational", label: "Educational" },
  { value: "tip",         label: "Tip / Insight" },
  { value: "case_study",  label: "Case Study" },
  { value: "check_in",    label: "Check-in" },
  { value: "custom",      label: "Custom" },
];

const DEFAULT_STEP = {
  content_type:  "educational",
  mode:          "ai_generated",
  ai_prompt_hint: "",
  template:       "",
};

function SequenceStep({ step, index, onChange, onRemove }) {
  return (
    <div className="border border-gray-200 rounded-lg p-4 bg-white space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-gray-700">
          Step {index + 1}
        </span>
        <button
          onClick={() => onRemove(index)}
          className="text-xs text-red-500 hover:text-red-700 font-medium"
        >
          Remove
        </button>
      </div>

      {/* Content type */}
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">
          Content Type
        </label>
        <select
          value={step.content_type}
          onChange={(e) => onChange(index, "content_type", e.target.value)}
          className="w-full text-sm border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {CONTENT_TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
      </div>

      {/* Mode toggle */}
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">
          Message Mode
        </label>
        <div className="flex gap-2">
          {["ai_generated", "custom"].map((m) => (
            <button
              key={m}
              onClick={() => onChange(index, "mode", m)}
              className={`flex-1 text-xs py-1.5 rounded-md border font-medium transition-colors ${
                step.mode === m
                  ? "bg-blue-600 text-white border-blue-600"
                  : "bg-white text-gray-600 border-gray-300 hover:border-blue-400"
              }`}
            >
              {m === "ai_generated" ? "AI Generated" : "Custom Template"}
            </button>
          ))}
        </div>
      </div>

      {/* Conditional content field */}
      {step.mode === "ai_generated" ? (
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            AI Prompt Hint
            <span className="text-gray-400 font-normal ml-1">
              (guides what topic Claude covers)
            </span>
          </label>
          <input
            type="text"
            value={step.ai_prompt_hint}
            onChange={(e) => onChange(index, "ai_prompt_hint", e.target.value)}
            placeholder="e.g. Share a tip about managing cash flow"
            maxLength={500}
            className="w-full text-sm border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      ) : (
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            Message Template
            <span className="text-gray-400 font-normal ml-1">
              (supports {"{{name}}"} and {"{{business_name}}"})
            </span>
          </label>
          <textarea
            value={step.template}
            onChange={(e) => onChange(index, "template", e.target.value)}
            placeholder={`Hi {{name}}, just checking in on how {{business_name}} is going…`}
            maxLength={1000}
            rows={3}
            className="w-full text-sm border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
          <p className="text-xs text-gray-400 mt-1">
            {step.template.length}/1000 characters
          </p>
        </div>
      )}
    </div>
  );
}

export default function NurtureSettings() {
  const [loading, setSaving]  = useState(false);
  const [saving, setSavingState] = useState(false);
  const [error, setError]     = useState(null);
  const [success, setSuccess] = useState(false);

  const [enabled, setEnabled]            = useState(false);
  const [conversionDays, setConversionDays] = useState(14);
  const [intervalDays, setIntervalDays]  = useState(7);
  const [sequence, setSequence]          = useState([]);

  useEffect(() => {
    setSaving(true);
    getNurtureConfig()
      .then((data) => {
        setEnabled(data.nurture_track_enabled ?? false);
        setConversionDays(data.conversion_attempt_days ?? 14);
        setIntervalDays(data.nurture_interval_days ?? 7);
        setSequence(
          (data.nurture_sequence || []).map((s) => ({
            content_type:  s.content_type  || "educational",
            mode:          s.mode          || "ai_generated",
            ai_prompt_hint: s.ai_prompt_hint || "",
            template:       s.template      || "",
          }))
        );
      })
      .catch((err) => setError(err.message || "Failed to load nurture config"))
      .finally(() => setSaving(false));
  }, []);

  function handleStepChange(index, field, value) {
    setSequence((prev) => {
      const updated = [...prev];
      updated[index] = { ...updated[index], [field]: value };
      return updated;
    });
  }

  function handleAddStep() {
    setSequence((prev) => [...prev, { ...DEFAULT_STEP }]);
  }

  function handleRemoveStep(index) {
    setSequence((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleSave() {
    setSavingState(true);
    setError(null);
    setSuccess(false);
    try {
      const payload = {
        nurture_track_enabled:   enabled,
        conversion_attempt_days: Number(conversionDays),
        nurture_interval_days:   Number(intervalDays),
        nurture_sequence: sequence.map((s, i) => ({
          position:       i + 1,
          content_type:  s.content_type,
          mode:          s.mode,
          ai_prompt_hint: s.mode === "ai_generated" ? s.ai_prompt_hint : null,
          template:       s.mode === "custom" ? s.template : null,
        })),
      };
      await updateNurtureConfig(payload);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      setError(err.response?.data?.detail?.message || err.message || "Failed to save");
    } finally {
      setSavingState(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
        Loading nurture settings…
      </div>
    );
  }

  return (
    <div className="max-w-2xl space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Lead Nurture Engine</h2>
        <p className="text-sm text-gray-500 mt-1">
          Stale leads that don't convert are automatically graduated to a nurture track where
          they receive periodic WhatsApp messages. When they reply, they're reactivated in the pipeline.
        </p>
      </div>

      {/* Enable toggle */}
      <div className="flex items-center justify-between p-4 border border-gray-200 rounded-lg bg-white">
        <div>
          <p className="text-sm font-medium text-gray-800">Enable Nurture Track</p>
          <p className="text-xs text-gray-500 mt-0.5">
            Automatically move inactive leads to a nurture sequence.
          </p>
        </div>
        <button
          onClick={() => setEnabled((v) => !v)}
          className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
            enabled ? "bg-blue-600" : "bg-gray-300"
          }`}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
              enabled ? "translate-x-6" : "translate-x-1"
            }`}
          />
        </button>
      </div>

      {/* Thresholds — only shown when enabled */}
      <div
        className={`space-y-4 transition-opacity ${enabled ? "opacity-100" : "opacity-40 pointer-events-none"}`}
      >
        <div className="grid grid-cols-2 gap-4">
          {/* Conversion attempt days */}
          <div className="p-4 border border-gray-200 rounded-lg bg-white">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Inactivity Window
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={1}
                max={365}
                value={conversionDays}
                onChange={(e) => setConversionDays(e.target.value)}
                className="w-20 text-sm border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <span className="text-sm text-gray-500">days</span>
            </div>
            <p className="text-xs text-gray-400 mt-1.5">
              Days without human activity before a lead graduates to nurture.
            </p>
          </div>

          {/* Nurture interval */}
          <div className="p-4 border border-gray-200 rounded-lg bg-white">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Message Interval
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={1}
                max={365}
                value={intervalDays}
                onChange={(e) => setIntervalDays(e.target.value)}
                className="w-20 text-sm border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <span className="text-sm text-gray-500">days</span>
            </div>
            <p className="text-xs text-gray-400 mt-1.5">
              Days between each nurture message sent to the lead.
            </p>
          </div>
        </div>

        {/* Sequence builder */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <div>
              <p className="text-sm font-medium text-gray-700">Message Sequence</p>
              <p className="text-xs text-gray-400">
                Steps repeat from the beginning when the sequence ends.
              </p>
            </div>
            <button
              onClick={handleAddStep}
              className="text-sm text-blue-600 hover:text-blue-800 font-medium border border-blue-200 rounded-md px-3 py-1.5 hover:bg-blue-50 transition-colors"
            >
              + Add Step
            </button>
          </div>

          {sequence.length === 0 ? (
            <div className="border-2 border-dashed border-gray-200 rounded-lg p-8 text-center">
              <p className="text-sm text-gray-400">No steps yet.</p>
              <p className="text-xs text-gray-300 mt-1">
                Add a step to start building your nurture sequence.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {sequence.map((step, i) => (
                <SequenceStep
                  key={i}
                  step={step}
                  index={i}
                  onChange={handleStepChange}
                  onRemove={handleRemoveStep}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Feedback */}
      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-md">
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}
      {success && (
        <div className="p-3 bg-green-50 border border-green-200 rounded-md">
          <p className="text-sm text-green-700">Nurture settings saved.</p>
        </div>
      )}

      {/* Save */}
      <div className="flex justify-end pt-2">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-5 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-md disabled:opacity-60 transition-colors"
        >
          {saving ? "Saving…" : "Save Settings"}
        </button>
      </div>
    </div>
  );
}

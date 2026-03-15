import type { ResearchJob } from "../types";

interface ResearchProgressBarProps {
  job: ResearchJob;
}

const STAGES = [
  { key: "researching", label: "Research", color: "bg-blue-500" },
  { key: "classifying", label: "Classify", color: "bg-indigo-500" },
  { key: "completed", label: "Contacts", color: "bg-green-500" },
] as const;

export default function ResearchProgressBar({ job }: ResearchProgressBarProps) {
  const total = job.total_companies || 1;
  const isFailed = job.status === "failed";
  const isCancelled = job.status === "cancelled" || job.status === "cancelling";

  // Determine which stage we're in and progress within it
  let currentStageIdx = 0;
  let stageProgress = 0;

  if (job.status === "completed") {
    currentStageIdx = 3; // Past all stages
    stageProgress = 100;
  } else if (isFailed || isCancelled) {
    if (job.classified_companies > 0) currentStageIdx = 2;
    else if (job.processed_companies > 0) currentStageIdx = 1;
    stageProgress = (job.processed_companies / total) * 100;
  } else if (job.status === "classifying") {
    currentStageIdx = 1;
    stageProgress = (job.classified_companies / total) * 100;
  } else if (job.status === "researching") {
    currentStageIdx = 0;
    stageProgress = (job.processed_companies / total) * 100;
  }

  // Overall progress for the simple bar
  let overallProgress = 0;
  if (job.status === "completed") overallProgress = 100;
  else if (job.status === "classifying") overallProgress = 50 + (job.classified_companies / total) * 50;
  else if (job.status === "researching") overallProgress = (job.processed_companies / total) * 50;
  else if (isFailed || isCancelled) overallProgress = (job.processed_companies / total) * 100;

  const isActive = !["completed", "failed", "cancelled"].includes(job.status);
  const barColor = isFailed ? "bg-red-500" : isCancelled ? "bg-gray-400" : "bg-blue-500";

  return (
    <div className="space-y-2">
      {/* Stage indicators */}
      <div className="flex items-center gap-1">
        {STAGES.map((stage, idx) => {
          const isDone = currentStageIdx > idx || job.status === "completed";
          const isCurrent = currentStageIdx === idx && isActive;

          return (
            <div key={stage.key} className="flex-1 flex items-center gap-1">
              <div className="flex-1">
                <div className="h-1.5 w-full rounded-full bg-gray-100 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ease-out ${
                      isDone ? stage.color :
                      isCurrent ? `${stage.color} ${isActive ? "animate-pulse" : ""}` :
                      isFailed ? "bg-red-300" :
                      "bg-gray-200"
                    }`}
                    style={{
                      width: isDone ? "100%" :
                             isCurrent ? `${stageProgress}%` :
                             "0%",
                    }}
                  />
                </div>
                <p className={`text-[10px] mt-0.5 ${
                  isDone ? "text-gray-700 font-medium" :
                  isCurrent ? "text-blue-600 font-medium" :
                  "text-gray-400"
                }`}>
                  {stage.label}
                </p>
              </div>
              {idx < STAGES.length - 1 && (
                <div className={`w-1 h-1 rounded-full shrink-0 mb-3 ${
                  isDone ? "bg-gray-400" : "bg-gray-200"
                }`} />
              )}
            </div>
          );
        })}
      </div>

      {/* Counter text */}
      <div className="flex items-center justify-between text-[11px]">
        <span className={`font-medium ${isFailed ? "text-red-600" : isCancelled ? "text-gray-500" : "text-gray-600"}`}>
          {isFailed ? "Failed" : isCancelled ? "Cancelled" : job.status === "completed" ? "Done" :
           job.status === "classifying" ? "Classifying..." : "Researching..."}
        </span>
        <span className="tabular-nums text-gray-400">
          {job.processed_companies}/{total} researched
          {job.classified_companies > 0 && ` · ${job.classified_companies} classified`}
          {job.contacts_discovered > 0 && ` · ${job.contacts_discovered} contacts`}
        </span>
      </div>
    </div>
  );
}

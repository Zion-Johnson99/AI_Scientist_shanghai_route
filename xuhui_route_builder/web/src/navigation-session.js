export function createNavigationSession(plan) {
  const path = normalizePath(plan?.path);
  if (path.length < 2) {
    throw new Error("接驳路径缺少可预览的坐标数据。");
  }

  const totalDistanceM = positiveNumber(plan?.distance);
  return {
    status: "previewing",
    path,
    steps: normalizeSteps(plan?.steps, totalDistanceM),
    totalDistanceM,
    totalDurationS: positiveNumber(plan?.duration),
    currentStepIndex: 0,
  };
}

export function navigationPreviewState(session) {
  const steps = session?.steps || [];
  if (!steps.length) {
    throw new Error("导航预览缺少分步指引。");
  }

  const currentStepIndex = clamp(
    Number(session.currentStepIndex) || 0,
    0,
    steps.length - 1,
  );
  const currentStep = steps[currentStepIndex];
  const completedDistanceM = steps
    .slice(0, currentStepIndex)
    .reduce((sum, step) => sum + step.distance, 0);
  const stepDistanceTotalM = steps.reduce((sum, step) => sum + step.distance, 0);

  return {
    status: session.status,
    currentStepIndex,
    stepNumber: currentStepIndex + 1,
    stepCount: steps.length,
    instruction: currentStep.instruction,
    stepDistanceM: currentStep.distance,
    totalDistanceM: session.totalDistanceM,
    totalDurationS: session.totalDurationS,
    progressRatio: stepDistanceTotalM ? completedDistanceM / stepDistanceTotalM : 0,
    canGoPrevious: session.status === "previewing" && currentStepIndex > 0,
    canGoNext: session.status === "previewing" && currentStepIndex < steps.length - 1,
  };
}

export function createNavigationController({ onProgress, onEnd } = {}) {
  let session = null;

  function currentSession() {
    if (!session || session.status !== "previewing") {
      throw new Error("导航预览尚未开始。");
    }
    return session;
  }

  function emitProgress() {
    const state = navigationPreviewState(currentSession());
    onProgress?.(state);
    return state;
  }

  return {
    start(plan) {
      session = createNavigationSession(plan);
      return emitProgress();
    },
    previous() {
      const activeSession = currentSession();
      activeSession.currentStepIndex = Math.max(0, activeSession.currentStepIndex - 1);
      return emitProgress();
    },
    next() {
      const activeSession = currentSession();
      activeSession.currentStepIndex = Math.min(
        activeSession.steps.length - 1,
        activeSession.currentStepIndex + 1,
      );
      return emitProgress();
    },
    stop() {
      if (!session) {
        return { status: "idle" };
      }
      session.status = "idle";
      const state = navigationPreviewState(session);
      onEnd?.(state);
      return state;
    },
    getSession() {
      return session;
    },
  };
}

function normalizePath(path) {
  return (path || [])
    .map((point) => {
      if (Array.isArray(point)) {
        return [Number(point[0]), Number(point[1])];
      }
      const lng = Number(point?.lng ?? point?.longitude ?? point?.getLng?.());
      const lat = Number(point?.lat ?? point?.latitude ?? point?.getLat?.());
      return [lng, lat];
    })
    .filter(([lng, lat]) => Number.isFinite(lng) && Number.isFinite(lat));
}

function normalizeSteps(steps, totalDistanceM) {
  const normalized = (steps || []).map((step) => ({
    instruction: String(step?.instruction || step?.action || "沿接驳路线继续前行"),
    distance: positiveNumber(step?.distance),
  }));
  if (!normalized.length) {
    return [{
      instruction: "沿接驳路线前往运动路线起点",
      distance: totalDistanceM,
    }];
  }

  const knownDistanceM = normalized.reduce((sum, step) => sum + step.distance, 0);
  if (knownDistanceM || !totalDistanceM) {
    return normalized;
  }
  const fallbackDistanceM = totalDistanceM / normalized.length;
  return normalized.map((step) => ({ ...step, distance: fallbackDistanceM }));
}

function positiveNumber(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) && number > 0 ? number : 0;
}

function clamp(value, lower, upper) {
  return Math.min(upper, Math.max(lower, value));
}

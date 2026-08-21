const EARTH_RADIUS_M = 6371008.8;
const DEFAULT_OFF_ROUTE_THRESHOLD_M = 50;
const DEFAULT_ARRIVAL_THRESHOLD_M = 25;

export function createNavigationSession(plan, options = {}) {
  const path = normalizePath(plan?.path);
  if (path.length < 2) {
    throw new Error("接驳路径缺少可导航的坐标数据。");
  }

  const geometryDistanceM = pathDistance(path);
  const totalDistanceM = positiveNumber(plan.distance) || geometryDistanceM;
  return {
    status: "navigating",
    path,
    steps: normalizeSteps(plan.steps, totalDistanceM),
    totalDistanceM,
    totalDurationS: positiveNumber(plan.duration),
    geometryDistanceM,
    offRouteThresholdM: positiveNumber(options.offRouteThresholdM) || DEFAULT_OFF_ROUTE_THRESHOLD_M,
    arrivalThresholdM: positiveNumber(options.arrivalThresholdM) || DEFAULT_ARRIVAL_THRESHOLD_M,
  };
}

export function updateNavigationSession(session, rawPosition) {
  const position = normalizePosition(rawPosition);
  const nearest = nearestPointOnPath(position, session.path);
  const destination = session.path.at(-1);
  const destinationDistanceM = distanceMeters(position, destination);
  const progressRatio = clamp(nearest.traveledGeometryM / session.geometryDistanceM, 0, 1);
  const arrived = destinationDistanceM <= session.arrivalThresholdM;
  const offRoute = !arrived && nearest.distanceM > session.offRouteThresholdM;
  const remainingDistanceM = arrived ? 0 : Math.max(0, session.totalDistanceM * (1 - progressRatio));
  const remainingDurationS = session.totalDurationS
    ? Math.max(0, session.totalDurationS * (1 - progressRatio))
    : 0;
  const status = arrived ? "arrived" : offRoute ? "off_route" : "navigating";

  session.status = status;
  return {
    status,
    position,
    progressRatio: arrived ? 1 : progressRatio,
    remainingDistanceM,
    remainingDurationS,
    distanceFromRouteM: nearest.distanceM,
    shouldReroute: offRoute,
    instruction: arrived ? "已到达运动路线起点" : instructionAt(session.steps, progressRatio),
    traveledPath: [...session.path.slice(0, nearest.segmentIndex + 1), nearest.point],
    remainingPath: [nearest.point, ...session.path.slice(nearest.segmentIndex + 1)],
  };
}

export function createNavigationController({ geolocation, onProgress, onError } = {}) {
  let watchId = null;
  let session = null;

  function stop() {
    if (watchId !== null) {
      geolocation?.clearWatch(watchId);
      watchId = null;
    }
  }

  return {
    start(plan, options) {
      stop();
      if (!geolocation?.watchPosition) {
        throw new Error("当前浏览器未提供实时定位能力。");
      }
      session = createNavigationSession(plan, options);
      watchId = geolocation.watchPosition(
        (result) => {
          const progress = updateNavigationSession(session, {
            lng: result.coords.longitude,
            lat: result.coords.latitude,
            accuracy: result.coords.accuracy,
            heading: result.coords.heading,
            timestamp: result.timestamp,
          });
          onProgress?.(progress);
          if (progress.status === "arrived") {
            stop();
          }
        },
        (error) => onError?.(new Error(locationErrorMessage(error))),
        {
          enableHighAccuracy: true,
          maximumAge: 1000,
          timeout: 10000,
        },
      );
      return session;
    },
    replacePlan(plan, options) {
      session = createNavigationSession(plan, options);
      return session;
    },
    stop,
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
    return [{ instruction: "沿接驳路线前往运动路线起点", endRatio: 1 }];
  }

  const stepDistanceTotal = normalized.reduce((sum, step) => sum + step.distance, 0);
  let cumulative = 0;
  return normalized.map((step, index) => {
    const ratio = stepDistanceTotal
      ? step.distance / stepDistanceTotal
      : 1 / normalized.length;
    cumulative += ratio;
    return {
      instruction: step.instruction,
      endRatio: index === normalized.length - 1 ? 1 : clamp(cumulative, 0, 1),
      distance: step.distance || totalDistanceM * ratio,
    };
  });
}

function instructionAt(steps, progressRatio) {
  return steps.find((step) => progressRatio < step.endRatio)?.instruction
    || steps.at(-1)?.instruction
    || "沿接驳路线继续前行";
}

function nearestPointOnPath(position, path) {
  let best = null;
  let cumulativeGeometryM = 0;
  for (let index = 0; index < path.length - 1; index += 1) {
    const start = path[index];
    const end = path[index + 1];
    const segmentLengthM = distanceMeters(start, end);
    const projection = projectToSegment(position, start, end);
    const candidate = {
      point: projection.point,
      distanceM: distanceMeters(position, projection.point),
      segmentIndex: index,
      traveledGeometryM: cumulativeGeometryM + segmentLengthM * projection.ratio,
    };
    if (!best || candidate.distanceM < best.distanceM) {
      best = candidate;
    }
    cumulativeGeometryM += segmentLengthM;
  }
  return best;
}

function projectToSegment(position, start, end) {
  const referenceLat = (start[1] + end[1] + position.lat) / 3;
  const scaleX = Math.cos(referenceLat * Math.PI / 180);
  const ax = start[0] * scaleX;
  const ay = start[1];
  const bx = end[0] * scaleX;
  const by = end[1];
  const px = position.lng * scaleX;
  const py = position.lat;
  const dx = bx - ax;
  const dy = by - ay;
  const denominator = dx * dx + dy * dy;
  const ratio = denominator ? clamp(((px - ax) * dx + (py - ay) * dy) / denominator, 0, 1) : 0;
  return {
    ratio,
    point: [start[0] + (end[0] - start[0]) * ratio, start[1] + (end[1] - start[1]) * ratio],
  };
}

function pathDistance(path) {
  let total = 0;
  for (let index = 0; index < path.length - 1; index += 1) {
    total += distanceMeters(path[index], path[index + 1]);
  }
  return total;
}

function distanceMeters(left, right) {
  const leftLng = Array.isArray(left) ? left[0] : left.lng;
  const leftLat = Array.isArray(left) ? left[1] : left.lat;
  const rightLng = Array.isArray(right) ? right[0] : right.lng;
  const rightLat = Array.isArray(right) ? right[1] : right.lat;
  const latitudeDelta = toRadians(rightLat - leftLat);
  const longitudeDelta = toRadians(rightLng - leftLng);
  const startLat = toRadians(leftLat);
  const endLat = toRadians(rightLat);
  const value = Math.sin(latitudeDelta / 2) ** 2
    + Math.cos(startLat) * Math.cos(endLat) * Math.sin(longitudeDelta / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(value)));
}

function normalizePosition(position) {
  const normalized = {
    lng: Number(position?.lng ?? position?.longitude),
    lat: Number(position?.lat ?? position?.latitude),
    accuracy: Number(position?.accuracy || 0),
    heading: Number.isFinite(Number(position?.heading)) ? Number(position.heading) : null,
    timestamp: Number(position?.timestamp || Date.now()),
  };
  if (!Number.isFinite(normalized.lng) || !Number.isFinite(normalized.lat)) {
    throw new Error("实时定位缺少有效经纬度。");
  }
  return normalized;
}

function positiveNumber(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) && number > 0 ? number : 0;
}

function locationErrorMessage(error) {
  const reasons = {
    1: "定位权限未开启，请允许浏览器访问当前位置。",
    2: "暂时无法获取当前位置，请到室外或检查系统定位服务。",
    3: "定位请求超时，请重试。",
  };
  return reasons[error?.code] || `实时定位失败：${error?.message || "未知错误"}`;
}

function toRadians(value) {
  return value * Math.PI / 180;
}

function clamp(value, lower, upper) {
  return Math.min(upper, Math.max(lower, value));
}

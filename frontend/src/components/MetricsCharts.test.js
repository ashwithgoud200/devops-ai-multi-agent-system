import test from "node:test";
import assert from "node:assert/strict";
import { classifyStatus, collectSeries } from "./metricsData.js";

test("classifyStatus classifies unlabelled, HTTP codes, and legacy strings", () => {
  assert.equal(classifyStatus(undefined), "unlabelled");
  assert.equal(classifyStatus(""), "unlabelled");
  assert.equal(classifyStatus("200"), "success");
  assert.equal(classifyStatus(200), "success");
  assert.equal(classifyStatus("204"), "success");
  assert.equal(classifyStatus("ok"), "success");
  assert.equal(classifyStatus("500"), "failed");
  assert.equal(classifyStatus(500), "failed");
  assert.equal(classifyStatus("503"), "failed");
  assert.equal(classifyStatus("404"), "failed");
  assert.equal(classifyStatus("error"), "failed");
  assert.equal(classifyStatus("client_error"), "failed");
  assert.equal(classifyStatus("other"), "other");
});

test("collectSeries returns null for missing or empty observations", () => {
  assert.equal(collectSeries(null), null);
  assert.equal(collectSeries({}), null);
  assert.equal(collectSeries({ metrics: {} }), null);
  assert.equal(collectSeries({ metrics: { request_rate: { observations: [] } } }), null);
});

test("collectSeries handles unlabelled aggregated series without assuming success", () => {
  const metrics = {
    metrics: {
      request_rate: {
        status: "ok",
        observations: [
          {
            labels: {},
            values: [
              { timestamp: 100, value: 0.762, stale: false },
              { timestamp: 160, value: 0.810, stale: false },
            ],
          },
        ],
      },
    },
  };

  const result = collectSeries(metrics);
  assert.ok(result);
  assert.equal(result.hasStatus, false);
  assert.equal(result.points.length, 2);
  assert.equal(result.points[0].total, 0.762);
  // Must NOT assume unlabelled total is successful
  assert.equal(result.points[0].success, 0);
  assert.equal(result.points[0].failed, 0);
});

test("collectSeries correctly classifies HTTP status labels (200, 500)", () => {
  const metrics = {
    metrics: {
      request_rate: {
        status: "ok",
        observations: [
          {
            labels: { job: "calculator-app", status: "200" },
            values: [{ timestamp: 100, value: 1.5, stale: false }],
          },
          {
            labels: { job: "calculator-app", status: "500" },
            values: [{ timestamp: 100, value: 0.3, stale: false }],
          },
        ],
      },
    },
  };

  const result = collectSeries(metrics);
  assert.ok(result);
  assert.equal(result.hasStatus, true);
  assert.equal(result.points.length, 1);
  assert.equal(result.points[0].total, 1.8);
  assert.equal(result.points[0].success, 1.5);
  assert.equal(result.points[0].failed, 0.3);
});

test("collectSeries correctly classifies legacy status labels (ok, error, client_error)", () => {
  const metrics = {
    metrics: {
      request_rate: {
        status: "ok",
        observations: [
          {
            labels: { status: "ok" },
            values: [{ timestamp: 200, value: 10, stale: false }],
          },
          {
            labels: { status: "client_error" },
            values: [{ timestamp: 200, value: 2, stale: false }],
          },
          {
            labels: { status: "error" },
            values: [{ timestamp: 200, value: 1, stale: false }],
          },
        ],
      },
    },
  };

  const result = collectSeries(metrics);
  assert.ok(result);
  assert.equal(result.hasStatus, true);
  assert.equal(result.points[0].total, 13);
  assert.equal(result.points[0].success, 10);
  assert.equal(result.points[0].failed, 3);
});

test("collectSeries ignores stale points and returns null if all points are stale", () => {
  const allStale = {
    metrics: {
      request_rate: {
        status: "unavailable",
        observations: [
          {
            labels: {},
            values: [
              { timestamp: 100, value: 1.0, stale: true },
              { timestamp: 160, value: 2.0, stale: true },
            ],
          },
        ],
      },
    },
  };
  assert.equal(collectSeries(allStale), null);

  const mixedStale = {
    metrics: {
      request_rate: {
        status: "ok",
        observations: [
          {
            labels: {},
            values: [
              { timestamp: 100, value: 1.0, stale: true },
              { timestamp: 160, value: 2.0, stale: false },
            ],
          },
        ],
      },
    },
  };
  const mixedResult = collectSeries(mixedStale);
  assert.ok(mixedResult);
  assert.equal(mixedResult.points.length, 1);
  assert.equal(mixedResult.points[0].timestamp, 160);
});

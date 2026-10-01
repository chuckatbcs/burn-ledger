---
version: alpha
colors:
  background: "#0b1016"
  surface: "#111820"
  surfaceRaised: "#16212b"
  border: "#263544"
  text: "#e7eef6"
  muted: "#8ca0b3"
  cyan: "#4bb4c9"
  amber: "#e6a23c"
  green: "#67b88a"
  danger: "#e06c75"
typography:
  display:
    fontFamily: "DejaVu Sans Condensed, Liberation Sans Narrow, system-ui, sans-serif"
  body:
    fontFamily: "DejaVu Sans, Liberation Sans, system-ui, sans-serif"
  data:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, Liberation Mono, monospace"
rounded:
  panel: "10px"
  control: "6px"
spacing:
  compact: "10px"
  standard: "16px"
  section: "24px"
components:
  panel:
    border: "1px solid #263544"
  statusBadge:
    shape: "pill"
  quotaRuler:
    signature: "segmented instrument rail"
---

## Overview
Burn Ledger should feel like an engineering control desk, not a consumer analytics template. The signature element is the four-tier recommendation board: each tier reads like an instrument lane with ranked model choices, evidence state, and completed-task cost. Restraint wins everywhere else; detailed telemetry stays out of the primary decision surface.

## Colors
Cyan means verified/active instrumentation, amber means changing or provisional evidence, green means measured/accepted status, and red is reserved for failed source checks or destructive states. Static panels remain blue-black and low contrast so data, not decoration, carries hierarchy.

## Typography
Display text is condensed and compact. Data, rates, timestamps, and IDs use monospace. Body copy stays highly legible and relatively small because this is an operator dashboard, not marketing UI.

## Layout
Desktop uses dense control-room grids with internal table scrolling. Narrow screens collapse to one column without hiding data or actions. The sticky section bar owns navigation; panels own their own table overflow.

## Elevation & Depth
Static content is mostly flat with a subtle deep shadow on primary panels. No floating-card collage.

## Shapes
Small radii only. Pills are limited to statuses and counts. Controls use compact rounded rectangles.

## Components
Tables use semantic HTML. Change events are a compact audit feed with explicit dismiss/retry/pause actions. Source health uses green/red status badges plus text, never color alone. Catalog tables expose compact sortable headers and a stable pagination footer. Search has a dedicated clear action. Async actions expose stable busy states without moving controls.

## Do's and Don'ts
Do preserve evidence labels beside numerical claims. Do distinguish measured, official, candidate, and heuristic states. Don't use gradients, oversized metric cards, glassmorphism, or decorative AI motifs. Don't color a row as a winner without naming the optimization objective.


## Availability controls
Provider and model availability use compact switch-buttons with text state (“In rotation” / “Excluded”) so color is never the only signal. Excluded rows remain readable but visually recede; the switch itself stays fully opaque and operable. Recommendation cards show a warning badge only when availability has changed the baseline measured route.


## Recommendation board
The Overview recommendation board is the primary visual hierarchy. Tier cards use a narrow semantic edge marker, compact task-example chips, and three ranked rows. Rank #1 gets restrained emphasis, but every row keeps its evidence badge and cost basis visible. Secondary metrics are small operator readouts, not oversized KPI hero cards.

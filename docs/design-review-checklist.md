# Design Review Checklist — Brew GIS

A structured heuristic checklist for periodic design audits. Each workspace surface
is evaluated against categories covering information architecture, data presentation,
navigation, workflow integrity, error/empty states, consistency, and accessibility.

## How to Use

1. **Pick a surface** from the table of contents below.
2. **Open the application** and navigate to a representative page for that surface
   (e.g., open a workspace detail page for the Data Catalog audit).
3. **Score each heuristic** as Pass (P), Fail (F), or Not Applicable (N/A).
4. **Add notes** — what works, what doesn't, what should change.
5. **Tag findings** by severity: `[CRITICAL]` (blocks user task), `[MAJOR]` (significant UX friction),
   `[MINOR]` (polish/cosmetic), `[OBSERVATION]` (subjective but worth discussing).
6. **File issues** for failures in the project's issue tracker.

---

## 1. Workspace Detail Hub (Data Catalog + Analysis Modules)

### Information Architecture

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Region summary (county/state info) is visible at the top of the page | | |
| 2 | Data Catalog and Analysis Modules are in side-by-side panels for comparison | | |
| 3 | Recent runs are below the panels, not interleaved | | |
| 4 | Information density is appropriate: table for structured data, cards for modules | | |

### Data Presentation

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Data Catalog table shows Source, Description, and Status columns | | |
| 2 | Status badges use consistent color semantics (green=imported, gray=not imported) | | |
| 3 | All 6 configured source types are listed | | |
| 4 | Analysis Modules show name, description, inputs, and outputs | | |
| 5 | Module prerequisite badges reflect actual data availability | | |

### Navigation & Orientation

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Quick-action bar is present with View Map, Import Data, Run Analysis | | |
| 2 | User can reach any related surface (map, import, analysis) from this page | | |
| 3 | Workspace name is prominent in the h1 header | | |

### Error & Empty States

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Empty workspace shows "No data sources configured" or "Not Imported" statuses | | |
| 2 | No runs shows helpful message, not an empty table | | |
| 3 | Missing prerequisite data is indicated by module badges | | |

---

## 2. Import Center

### Information Architecture

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Import methods are organized into logical tabs (upload, POI, census, stitch) | | |
| 2 | Each tab has a clear title and description | | |
| 3 | Related options are grouped (census sub-tabs for ACS vs LEHD) | | |
| 4 | Recent imports section shows last import activity | | |

### Data Presentation

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Forms show field labels, help text, and input types clearly | | |
| 2 | Import type names are descriptive ("Upload File" vs "Points of Interest") | | |
| 3 | Status badges on recent imports use consistent color scheme | | |

### Navigation & Orientation

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Breadcrumb shows Home > Import Data | | |
| 2 | Active tab is visually distinct | | |
| 3 | User can switch between tabs without data loss | | |

### Error & Empty States

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | No recent imports shows "Recent Imports" section hidden or empty state | | |
| 2 | Form validation errors are visible and actionable | | |
| 3 | Preview results (census, POI) show clear success/failure messages | | |

---

## 3. Map + Paint

### Information Architecture

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Map component occupies the primary visual area | | |
| 2 | Scenario selector is easily accessible (not hidden) | | |
| 3 | Paint toolbar is visible and logically positioned near the map | | |

### Data Presentation

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Map renders tiles for the selected workspace area | | |
| 2 | Layer list shows available layers for the workspace | | |
| 3 | Built forms dropdown provides building/place type selection | | |

### Navigation & Orientation

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Back navigation is available (Back button/link) | | |
| 2 | Undo/redo controls are present in the paint toolbar | | |
| 3 | User can navigate to symbology editor from the map | | |

### Workflow Integrity

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Complete workflow: import data → view on map → run analysis | | |
| 2 | Scenario switching updates the map display | | |
| 3 | Paint edits can be saved and reset | | |

---

## 4. Analysis Pipeline

### Information Architecture

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Launch form clearly shows required analysis parameters | | |
| 2 | Module selection is organized and scannable | | |
| 3 | Runs list shows workspace, modules, status, and timestamp | | |

### Data Presentation

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Run status uses color-coded badges (green=completed, blue=running, red=failed) | | |
| 2 | Run detail view shows modules, started/completed times, and error logs | | |
| 3 | Progress indicator is shown for running analyses | | |

### Navigation & Orientation

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | "New Run" button is accessible from the list page | | |
| 2 | User can navigate from run detail back to all runs | | |
| 3 | Breadcrumb or back-link provides orientation | | |

### Error & Empty States

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | No runs shows "No analysis runs yet" with a CTA to launch | | |
| 2 | Failed runs show error details (not just "failed") | | |
| 3 | Missing prerequisites are explained in the launch form | | |

---

## 5. Built Forms (Building Types, Place Types, Mix)

### Information Architecture

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Building types and place types have separate list pages | | |
| 2 | Cards show name, density, and key parameters | | |
| 3 | Create/edit forms have logical field groupings | | |

### Data Presentation

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Card layout is scannable with consistent title placement | | |
| 2 | Density and allocation percentages are clearly labeled | | |
| 3 | Mix configuration (place type ↔ building type) is intuitive | | |

### Navigation & Orientation

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Create button is visible on list pages | | |
| 2 | Edit links are accessible from card/list items | | |
| 3 | Bake button is accessible for applying built form changes | | |

### Error & Empty States

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | No building types shows "No building types" empty state | | |
| 2 | Form validation errors are shown inline | | |

---

## 6. Symbology Editor

### Information Architecture

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Symbology type selector is prominent at the top of the form | | |
| 2 | Color controls (default, stroke) are grouped together | | |
| 3 | Style class table is organized by label, color, min/max | | |

### Data Presentation

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Available symbology types are explicitly listed (Single, Categorical, Graduated) | | |
| 2 | Color pickers show the current color value | | |
| 3 | Classification options appear contextually (not for single symbol) | | |

### Navigation & Orientation

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Page title shows "Symbology: {layer name}" | | |
| 2 | Back to Map link is present | | |
| 3 | Save, Auto-Generate, and Preview actions are accessible | | |

### Error & Empty States

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | No style classes shows an empty or hidden table (not broken) | | |
| 2 | Missing attribute column shows placeholder text | | |

---

## 7. Cross-Surface Consistency

### Navigation & Orientation

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | All workspace surfaces have a consistent navbar | | |
| 2 | Breadcrumbs are present on sub-pages (import center, analysis, editor) | | |
| 3 | Page titles are descriptive and follow a consistent pattern | | |
| 4 | Workspace context is maintained when navigating between surfaces | | |

### Consistency

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | Table styles, card layouts, badge patterns are consistent across surfaces | | |
| 2 | Button styles follow consistent patterns (primary, outline, danger) | | |
| 3 | Form patterns (labels, help text, validation) are consistent | | |
| 4 | Terminology is consistent (e.g., "Import" not "Fetch" or "Load") | | |

### Error & Empty States

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | All surfaces handle empty state with helpful messaging | | |
| 2 | Error messages are actionable (tell user what to do) | | |
| 3 | Loading/network states are indicated | | |

### Accessibility

| # | Heuristic | Pass/Fail | Notes |
|---|---|---|---|
| 1 | All interactive elements are keyboard-navigable | | |
| 2 | Color is not the only differentiator for status (icons + text + color) | | |
| 3 | Form inputs have visible, associated labels | | |
| 4 | Navigation has clear focus indicators | | |
| 5 | Page structure uses semantic HTML (headings, landmarks) | | |

---

## Review Log

| Date | Reviewer | Surfaces Covered | Findings | Next Review |
|---|---|---|---|---|
| | | | | |

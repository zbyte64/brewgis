Feature: Analysis Modules UX
  As a user viewing the workspace detail hub
  I want to see available analysis modules and their prerequisites
  So that I can understand which analyses are ready to run

  Background:
    Given the user is logged in

  @review
  Scenario: Analysis modules panel displays all modules
    Given a workspace named "Analysis WS" exists
    When I navigate to the workspace detail page
    Then the Analysis Modules panel should have 4 modules
    And the modules should include "Environmental Constraint"
    And the modules should include "Core Allocation"
    And the modules should include "Water Demand"
    And the modules should include "Energy Demand"

  @review
  Scenario: Each analysis module shows name, description, inputs, and outputs
    Given a workspace named "Module Detail" exists
    When I navigate to the workspace detail page
    Then the "Environmental Constraint" module should have description "Overlay environmental constraints on base parcels"
    And the "Environmental Constraint" module should list inputs "Base parcels", "Constraint layers"
    And the "Environmental Constraint" module should list outputs "Environmental constraint overlay"
    And the "Core Allocation" module should show input "Scenario parameters"

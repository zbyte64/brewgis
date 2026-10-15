Feature: Workspace Map
  As a logged-in user
  I want to view a workspace map
  So that I can see my layers visualized

  Background:
    Given the user is logged in
    And a workspace named "Map Test WS" exists

  @e2e
  Scenario: Map page renders with web component
    When I navigate to the map page for workspace "Map Test WS"
    Then Map - Map Test WS in the page title
    And the map web component should be visible
    And I should see a "Back" button

  @e2e
  Scenario: Map page requires authentication
    Given the user is not logged in
    When I navigate to the map page for workspace "Map Test WS"
    Then I should be on the login page

  @e2e
  Scenario: Another tab's layer change reaches the open map without a reload
    Given the workspace "Map Test WS" has a layer named "Live Layer"
    When I navigate to the map page for workspace "Map Test WS"
    And the map's live update connection is open
    And another tab hides the layer "Live Layer"
    Then the map shows the layer "Live Layer" as hidden without reloading

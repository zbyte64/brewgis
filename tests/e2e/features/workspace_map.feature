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
    Then I should see "Map - Map Test WS" in the page title
    And the map web component should be visible
    And I should see a "Back" button

  @e2e
  Scenario: Map page requires authentication
    Given the user is not logged in
    When I navigate to the map page for workspace "Map Test WS"
    Then I should be on the login page

Feature: Map + Paint UX
  As a user viewing the workspace map
  I want the map and paint tools to be accessible
  So that I can visualize and edit my workspace data

  Background:
    Given the user is logged in

  @review
  Scenario: Map page renders web component and navigation
    Given a workspace named "Map WS" exists
    When I navigate to the map page
    Then the map web component should be visible
    And I should see a "Back" button

  @review
  Scenario: Map page has scenario selector
    Given a workspace named "Scenario WS" exists
    When I navigate to the map page
    Then the scenario dropdown should be visible

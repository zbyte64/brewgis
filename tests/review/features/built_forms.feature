Feature: Built Forms UX
  As a user managing built forms
  I want the building type and place type library to be reachable from the map
  So that I can configure land use definitions without leaving my work

  Background:
    Given the user is logged in
    And a workspace named "Built Forms WS" exists

  @review
  Scenario: Building types show in the map's Built Forms panel
    Given a building type named "Single Family" exists in the built forms workspace
    When I navigate to the building types page
    Then I should see built form rows
    And I should see "Single Family" in the rows

  @review
  Scenario: Place types show in the map's Built Forms panel
    Given a place type named "Residential" exists in the built forms workspace
    When I navigate to the place types page
    Then I should see built form rows
    And I should see "Residential" in the rows

  @review
  Scenario: The panel offers both create actions
    Given a building type named "Single Family" exists in the built forms workspace
    When I navigate to the building types page
    Then the panel should offer a new building type and a new place type
    And each built form row should offer edit and delete actions

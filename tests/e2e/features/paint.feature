Feature: Paint Mode
  As a logged-in user
  I want to paint scenario attributes on the map
  So that I can test different development scenarios

  Background:
    Given the user is logged in

  @e2e
  Scenario: Paint toolbar appears when scenario is selected
    Given a workspace "Paint WS Toolbar" with scenario "Test Scenario" exists
    When I navigate to the map page for workspace "Paint WS Toolbar"
    And I select "Test Scenario" from the scenario dropdown
    Then the scenario should be active
    And the Paint Mode button should be visible
    And the paint toolbar should be hidden

  @e2e
  Scenario: Paint mode toggle shows and hides the toolbar
    Given a workspace "Paint WS Toggle" with scenario "Test Scenario" exists
    And I am on the map page with "Test Scenario" and workspace "Paint WS Toggle"
    When I click "Paint Mode"
    Then the paint toolbar should be visible
    And the Apply button should be disabled
    And the Clear button should be disabled
    When I click "Paint Mode" again
    Then the paint toolbar should be hidden

  @e2e
  Scenario: Apply and Clear buttons enable when features are selected
    Given a workspace "Paint WS Buttons" with scenario "Test Scenario" exists
    And I am on the map page with "Test Scenario" and workspace "Paint WS Buttons"
    And paint mode is active
    When I select 3 parcels
    Then the feature count should show "3 parcel(s) selected"
    And the Apply button should be enabled
    And the Clear button should be enabled
    When I clear the selection
    Then the feature count should show "0 parcel(s) selected"
    And the Apply button should be disabled
    And the Clear button should be disabled

  @e2e
  Scenario: Scenario dropdown navigates the page
    Given a workspace "Paint WS Dropdown" with scenarios "Alpha" and "Beta"
    When I navigate to the map page for workspace "Paint WS Dropdown"
    And I select "Alpha" from the scenario dropdown
    Then the page URL should contain "scenario"
    And I select "Beta" from the scenario dropdown
    Then the page URL should contain "scenario"

Feature: Scenario Management UX
  As a user viewing the workspace detail hub
  I want to see scenario status and create new scenarios
  So that I can manage my workspace scenarios

  Background:
    Given the user is logged in

  @review
  Scenario: Scenario panel shows the workspace's base scenario by default
    Given a workspace named "Test Region" exists
    When I navigate to the workspace detail page
    Then I should see "Base Scenario"

  @review
  Scenario: Create scenario page shows the form
    Given a workspace named "Test Region" exists
    When I navigate to the create scenario page for that workspace
    Then I should see the scenario form

Feature: Workspace Creation
  As a logged-in user
  I want to create workspaces
  So that I can organize my map layers

  Background:
    Given the user is logged in

  @e2e
  Scenario: Create workspace page shows the form
    When I navigate to the create workspace page
    Then Create Workspace in the page title
    And I should see a "Name" form field

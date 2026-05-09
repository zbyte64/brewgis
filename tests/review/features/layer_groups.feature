Feature: Layer Groups UX
  As a user managing layers
  I want the workspace detail page to load successfully
  So that I can manage my map layers

  Background:
    Given the user is logged in

  @review
  Scenario: Workspace detail page loads for a workspace with layers
    Given a workspace named "Test Groups" exists
    And a layer named "Zoning" exists in workspace "Test Groups"
    When I navigate to the workspace detail page
    Then the page loads successfully

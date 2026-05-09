Feature: Cross-Surface Consistency UX
  As a user navigating the workspace
  I want consistent navigation and informative empty states across all pages
  So that I can find my way around the application

  Background:
    Given the user is logged in

  @review
  Scenario: Home page has navbar with navigation links
    Given a workspace named "Nav WS" exists
    When I navigate to the home page
    Then I should see the main navigation bar
    And I should see navigation links

  @review
  Scenario: Workspace surfaces have empty state messaging
    Given a workspace named "Empty WS" exists
    When I navigate to the workspace detail page
    Then the Analysis Modules panel should show empty state or modules

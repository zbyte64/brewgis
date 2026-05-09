Feature: Analysis Pipeline UX
  As a user running analyses
  I want the analysis pipeline to have clear launch form and status display
  So that I can run and monitor analyses effectively

  Background:
    Given the user is logged in

  @review
  Scenario: Analysis launch page shows form fields
    When I navigate to the analysis launch page
    Then I should see form fields on the launch page

  @review
  Scenario: Analysis list page shows runs or empty state
    Given a workspace named "Analysis List WS" exists
    When I navigate to the analysis list page
    Then I should see a "New Run" button
    And the page should show runs or empty state

  @review
  Scenario: Analysis list page has status badges for runs
    Given a workspace named "Status WS" exists
    When I navigate to the analysis list page
    Then status badges should be visible for listed runs

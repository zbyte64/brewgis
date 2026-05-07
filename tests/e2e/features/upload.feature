Feature: GIS File Upload
  As a logged-in user
  I want to upload GIS files to workspaces
  So that I can import geographic data

  Background:
    Given the user is logged in
    And a workspace named "Upload Test WS" exists

  @e2e
  Scenario: Upload page shows the form
    When I navigate to the upload page
    Then I should see "Importgis File" in the page title
    And I should see a file upload field

  @e2e
  Scenario: Submit without file shows validation error
    When I navigate to the upload page
    And I submit the form without a file
    Then I should see a validation error message

  @e2e
  Scenario: Upload requires authentication
    Given the user is not logged in
    When I navigate to the upload page
    Then I should be on the login page

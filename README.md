* **Purpose** Automate, end-to-end, the official Google-Cloud-Identity ↔ Microsoft-Entra-ID (Azure AD) federation guide—so an administrator can run a single, repeatable script instead of clicking through two consoles.

* **Design principles**

| Principle           | How it’s expressed in the JSON                                                                                                                 |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| **Idempotent**      | Every step begins with a **`verify`** call (a GET) that proves the resource is already in the desired state; if so, the mutating call is skipped. |
| **Least privilege** | Each step lists **`permissions_required`**—the minimal OAuth scopes / IAM roles that grant the call.                                           |
| **API only**        | Every console action is mapped to a REST endpoint; GA if available, **`apiStatus\": \"beta\"`** or **`\"preview\"`** if not.                   |
| **Sequenced**       | **`depends_on`** arrays impose the same ordering constraints described in the Google article (plus one extra gate: domain verification first). |
| **Variable flow**   | Step outputs (e.g., `samlProfileId`) are saved in **`variables_populated`** and reused by later steps via `{placeholder}` syntax.              |

* **Major phases**

1. **Domain gate** – aborts early if the custom domain isn’t verified.
2. **Google setup** – Automation OU → service user → custom admin role → inbound SAML profile.
3. **Azure provisioning app** – instantiate gallery app, patch credentials, start sync job.
4. **Azure SSO app** – instantiate second gallery app, patch SAML settings, add claims, assign users/groups.
5. **Google profile assignment** – preview API to bind the SAML profile to the organization root.
6. **Manual test** – final browser redirect; no API exists to emulate it.

The repository includes `openapi_subset.json`, extracted from official Google Discovery documents and Microsoft Graph OpenAPI. It lists only the methods referenced in `workflow.json`.

---

## 2 The complete JSON definition

```json
{
  "version": "3.0",
  "description": "Fully API-driven, idempotent workflow for federating Google Cloud with Microsoft Entra ID. GA endpoints wherever possible; beta/preview flagged. Every step starts with a READ pre-check so repeated runs are safe.",
  "steps": [
    {
      "id": "D-1",
      "name": "Verify custom domain in Google",
      "precheck": {"method": "GET", "path": "/admin/directory/v1/customer/{customerId}/domains/{domainName}"},
      "http": {"method": "POST", "path": "/admin/directory/v1/customer/{customerId}/domains", "payload": {"domainName": "{domainName}"}},
      "variables_required": ["customerId", "domainName", "googleAccessToken"],
      "permissions_required": ["admin.directory.domain", "siteverification"],
      "apiStatus": "GA"
    },

    {"id": "G-1", "name": "Create OU /Automation", "precheck": {"method": "GET", "path": "/admin/directory/v1/customer/{customerId}/orgunits?type=children&orgUnitPath=/"},
      "http": {"method": "POST", "path": "/admin/directory/v1/customer/{customerId}/orgunits", "payload": {"name": "Automation","parentOrgUnitPath": "/"}},
      "variables_required": ["customerId","googleAccessToken"], "permissions_required": ["admin.directory.orgunit"], "depends_on": ["D-1"], "apiStatus": "GA"},

    {"id": "G-2", "name": "Create service user", "precheck": {"method": "GET","path": "/admin/directory/v1/users/azuread-provisioning@{primaryDomain}"},
      "http": {"method": "POST", "path": "/admin/directory/v1/users", "payload": {"name": {"givenName": "Microsoft Entra ID","familyName": "Provisioning"}, "password": "{generatedPassword}", "primaryEmail": "azuread-provisioning@{primaryDomain}", "orgUnitPath": "/Automation"}},
      "variables_populated": ["provisioningUserId","provisioningUserEmail","provisioningUserPassword"],
      "variables_required": ["primaryDomain","googleAccessToken"], "permissions_required": ["admin.directory.user"], "depends_on": ["G-1"], "apiStatus": "GA"},

    {"id": "G-3", "name": "Create custom admin role", "precheck": {"method": "GET", "path": "/admin/directory/v1/customer/{customerId}/roles?query=roleName:Microsoft%20Entra%20Provisioning"},
      "http": {"method": "POST", "path": "/admin/directory/v1/customer/{customerId}/roles", "payload": {"roleName": "Microsoft Entra Provisioning", "privilegeIds": ["ORGANIZATION_UNITS_READ","USERS_ALL","GROUPS_ALL"]}},
      "variables_populated": ["adminRoleId"], "variables_required": ["customerId","googleAccessToken"], "permissions_required": ["admin.directory.rolemanagement"], "depends_on": ["G-2"], "apiStatus": "GA"},

    {"id": "G-3b", "name": "Assign role to service user", "precheck": {"method": "GET", "path": "/admin/directory/v1/customer/{customerId}/roleassignments?roleId={adminRoleId}&assignedTo={provisioningUserId}"},
      "http": {"method": "POST", "path": "/admin/directory/v1/customer/{customerId}/roleassignments", "payload": {"roleId": "{adminRoleId}", "assignedTo": "{provisioningUserId}", "scopeType": "CUSTOMER"}},
      "variables_required": ["adminRoleId","provisioningUserId","customerId","googleAccessToken"], "permissions_required": ["admin.directory.rolemanagement"], "depends_on": ["G-3"], "apiStatus": "GA"},

    {"id": "G-4", "name": "Create inbound SAML profile", "precheck": {"method": "GET", "path": "/v1beta1/inboundSamlSsoProfiles?filter=displayName%3DAzure%20AD"},
      "http": {"method": "POST", "path": "/v1beta1/inboundSamlSsoProfiles", "payload": {"displayName": "Azure AD", "customer": "customers/{customerId}"}},
      "variables_populated": ["samlProfileId","entityId","acsUrl"], "variables_required": ["customerId","googleAccessToken"], "permissions_required": ["cloud-identity.samlssoprofiles"], "depends_on": ["G-3b"], "apiStatus": "beta"},

    {"id": "A-1", "name": "Instantiate provisioning gallery app", "precheck": {"method": "GET", "path": "/v1.0/servicePrincipals?$filter=displayName eq 'Google Cloud (Provisioning)'"},
      "http": {"method": "POST", "path": "/v1.0/applicationTemplates/{provTemplateId}/instantiate", "payload": {"displayName": "Google Cloud (Provisioning)"}},
      "variables_populated": ["provServicePrincipalId"], "variables_required": ["provTemplateId","azureAccessToken"], "permissions_required": ["Application.ReadWrite.All"], "depends_on": ["G-3b"], "apiStatus": "GA"},

    {"id": "A-2", "name": "Configure provisioning creds", "precheck": {"method": "GET", "path": "/v1.0/servicePrincipals/{provServicePrincipalId}/synchronization"},
      "http": {"method": "PATCH", "path": "/v1.0/servicePrincipals/{provServicePrincipalId}/synchronization", "payload": {"credentials": {"fields": [{"name": "Username", "value": "{provisioningUserEmail}"},{"name": "Password", "value": "{provisioningUserPassword}"}]}, "schedule": {"interval": "PT40M"}, "templateId": "sync-schema-v2"}},
      "variables_required": ["provServicePrincipalId","provisioningUserEmail","provisioningUserPassword","azureAccessToken"], "permissions_required": ["Application.ReadWrite.All"], "depends_on": ["A-1"], "apiStatus": "GA"},

    {"id": "A-2b", "name": "Enable provisioning & start sync", "precheck": {"method": "GET", "path": "/v1.0/servicePrincipals/{provServicePrincipalId}/synchronization"},
      "http": {"method": "POST", "path": "/v1.0/servicePrincipals/{provServicePrincipalId}/synchronization/jobs", "payload": {"jobType": "Initial"}},
      "variables_required": ["provServicePrincipalId","azureAccessToken"], "permissions_required": ["Application.ReadWrite.All"], "depends_on": ["A-2"], "apiStatus": "GA"},

    {"id": "A-3", "name": "Instantiate SSO gallery app", "precheck": {"method": "GET", "path": "/v1.0/servicePrincipals?$filter=displayName eq 'Google Cloud'"},
      "http": {"method": "POST", "path": "/v1.0/applicationTemplates/{ssoTemplateId}/instantiate", "payload": {"displayName": "Google Cloud"}},
      "variables_populated": ["ssoServicePrincipalId"], "variables_required": ["ssoTemplateId","azureAccessToken"], "permissions_required": ["Application.ReadWrite.All"], "depends_on": ["G-4"], "apiStatus": "GA"},

    {"id": "A-4", "name": "Configure basic SAML settings", "precheck": {"method": "GET", "path": "/beta/servicePrincipals/{ssoServicePrincipalId}/samlSingleSignOnSettings"},
      "http": {"method": "PATCH", "path": "/beta/servicePrincipals/{ssoServicePrincipalId}/samlSingleSignOnSettings", "payload": {"identifierUris": ["{entityId}"], "replyUrls": ["{acsUrl}"]}},
      "variables_required": ["ssoServicePrincipalId","entityId","acsUrl","azureAccessToken"], "permissions_required": ["Application.ReadWrite.All"], "depends_on": ["A-3"], "apiStatus": "beta"},

    {"id": "A-4b", "name": "Add claims mapping policy", "precheck": {"method": "GET", "path": "/beta/servicePrincipals/{ssoServicePrincipalId}/tokenIssuancePolicies"},
      "http": {"method": "POST", "path": "/beta/policies/tokenIssuance", "payload": {"definition": ["{\"claimsMapping\":{...}}"]}},
      "variables_populated": ["claimsPolicyId"], "variables_required": ["azureAccessToken"], "permissions_required": ["Policy.ReadWrite.ApplicationConfiguration"], "depends_on": ["A-4"], "apiStatus": "beta"},

    {"id": "A-4c", "name": "Link policy to SP", "precheck": {"method": "GET", "path": "/beta/servicePrincipals/{ssoServicePrincipalId}/tokenIssuancePolicies"},
      "http": {"method": "POST", "path": "/beta/servicePrincipals/{ssoServicePrincipalId}/tokenIssuancePolicies/$ref", "payload": {"@odata.id": "https://graph.microsoft.com/beta/policies/tokenIssuancePolicies/{claimsPolicyId}"}},
      "variables_required": ["ssoServicePrincipalId","claimsPolicyId","azureAccessToken"], "permissions_required": ["Policy.ReadWrite.ApplicationConfiguration"], "depends_on": ["A-4b"], "apiStatus": "beta"},

    {"id": "A-5", "name": "Assign users/groups to SSO app", "precheck": {"method": "GET", "path": "/v1.0/servicePrincipals/{ssoServicePrincipalId}/appRoleAssignedTo?$filter=principalId eq {principalId}"},
      "http": {"method": "POST", "path": "/v1.0/servicePrincipals/{ssoServicePrincipalId}/appRoleAssignedTo", "payload": {"principalId": "{principalId}", "resourceId": "{ssoServicePrincipalId}", "appRoleId": "00000000-0000-0000-0000-000000000000"}},
      "variables_required": ["ssoServicePrincipalId","principalId","azureAccessToken"], "permissions_required": ["AppRoleAssignment.ReadWrite.All"], "depends_on": ["A-4c"], "apiStatus": "GA"},

    {"id": "G-5b", "name": "Assign SAML profile to org", "precheck": {"method": "GET", "path": "/v1beta1/inboundSamlSsoAssignments"},
      "http": {"method": "POST", "path": "/v1beta1/inboundSamlSsoAssignments", "payload": {"samlSsoProfile": "{samlProfileId}", "targetOrgUnit": "/"}},
      "variables_required": ["samlProfileId","googleAccessToken"], "permissions_required": ["cloud-identity.samlssoprofiles"], "depends_on": ["A-5"], "apiStatus": "preview"},

    {"id": "T-1", "name": "Trigger SSO test", "precheck": {"method": "GET", "path": "https://console.cloud.google.com?authuser=test"},
      "manual": true, "depends_on": ["G-5b"]}
  ]
}
```


### Goal A:
Will the workflow achieve the intended outcomes?

1. **Understand the outcomes.**
   *Successful federation* means:

   * Azure-managed users can log in to `https://console.cloud.google.com` via SAML without a Google password.
   * User & group objects sync (create/update/delete) from Entra ID to Google via the gallery connector.
   * Automation user in Google has only the minimum delegated privileges.

2. **Trace dependency graph.**
   Ensure the **`depends_on`** topology forms a DAG with `D-1` as the root and `T-1` as the leaf.

3. **Simulate variable flow.**
   Walk through steps: confirm that every placeholder (e.g., `{ssoServicePrincipalId}`) is produced by a prior **`variables_populated`** and consumed after.

4. **Check idempotence logic.**
   For every step with `precheck`, verify that:

   * The `precheck` call’s response uniquely determines “already done”.
   * If “done”, mutating call’s side-effects are safe to skip.

5. **Validate final state.**
   Build an expected state table (domain verified, OU exists, SPs exist, SAML profile bound, sync job active). Confirm each expected state is indeed the end-product of at least one workflow step.

---

### Goal
Are APIs, scopes, URLs, payload keys, sequence, variables accurate?

**Per step checklist for the model**

| Check                       | How to verify                                                                                                                                                                           |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Endpoint exists**         | Call Google Discovery (`https://cloudidentity.googleapis.com/$discovery/rest?version=v1beta1`) or Microsoft Graph `$metadata` (v1.0 or beta) and confirm `<path>` + `<method>` appears. |
| **OAuth scope suffices**    | Cross-look-up the endpoint in its doc and list required scopes; ensure `permissions_required` array contains at least one.                                                              |
| **Payload schema**          | Compare each JSON key in `payload` to the official schema (`components.schemas` in Discovery or CSDL in Graph).                                                                         |
| **`apiStatus` correctness** | GA endpoints should appear in v1.0; beta in /beta only; preview not in discovery by default.                                                                                            |
| **Variable placeholders**   | Confirm every `{variable}` matches exactly one entry in `variables_required` or `variables_populated`.                                                                                  |
| **Method semantics**        | For PATCH or POST, ensure the endpoint supports that verb (metadata describes it).                                                                                                      |
| **Sequence validity**       | Evaluate if any step relies on an ID that could be lazily provisioned by the provider (e.g., SP provisioning may take minutes)—if so, note race conditions and suggest retry/back-off.  |

---

**Recommended automated research routine**

1. **Fetch live API metadata**

   ```bash
   curl -s https://graph.microsoft.com/v1.0/$metadata > graph.xml
   curl -s https://graph.microsoft.com/beta/$metadata > graph-beta.xml
   curl -s "https://cloudidentity.googleapis.com/$discovery/rest?version=v1beta1" | jq . > ci.json
   curl -s "https://admin.googleapis.com/$discovery/rest?version=directory_v1" | jq . > dir.json
   ```

2. **Write a verifier script** (Python or Node) that:

   * Parses the JSON workflow.
   * For each step:

     * Confirms verb+path appear in the appropriate metadata file.
     * Confirms all payload keys exist in the schema.
     * Prints “PASS” / “FAIL” with explanations.

3. **Dry-run `precheck` calls** against a sandbox tenant with read-only tokens; expect HTTP 200/404 as coded.  Record any 401/403 (scope mismatch).

4. **(Optional) Canary full run** in throw-away tenants, capturing every response body to assert schema compatibility in practice.

5. **Monitor feeds**
   *Subscribe the verifying model (or a cron job) to*:

   * [https://developers.google.com/identity/release-notes.atom](https://developers.google.com/identity/release-notes.atom)
   * [https://learn.microsoft.com/api/search/rss?search=%22Microsoft+Graph+beta%22](https://learn.microsoft.com/api/search/rss?search=%22Microsoft+Graph+beta%22)
     Flag workflow steps when an endpoint deprecates or moves GA→beta, etc.

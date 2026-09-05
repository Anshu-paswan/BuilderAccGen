from flask import Flask, render_template, request, Response, stream_with_context, jsonify
import requests
import json
import time
import uuid
import re
import random
import string
import os
import urllib.parse

# ---------- Configuration ----------
FIREBASE_API_KEY = "AIzaSyDzqq-xY7RZuyjjBltPQXVDflkiviwoXlA"
SIGNUP_URL = "https://cdn.builder.io/api/v1/signup"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://builder.io/",
    "Origin": "https://builder.io",
    "Sec-GPC": "1",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Content-Type": "application/json",
}

# ---------- Save accounts ----------
def save_account(email, password, filename="accounts.txt"):
    try:
        os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
        with open(filename, "a", encoding="utf-8") as f:
            f.write(f"{email},{password}\n")
        return True
    except Exception as e:
        print(f"Error saving account: {e}")
        return False

# ---------- Mail.tm functions ----------
MAILTM_BASE = "https://api.mail.tm"

def create_mail(prefix=None, password=None):
    """Create a new Mail.tm account; if prefix is None, generate random."""
    resp = requests.get(f"{MAILTM_BASE}/domains")
    resp.raise_for_status()
    domains = resp.json()["hydra:member"]
    if not domains:
        raise Exception("No Mail.tm domains available")
    domain = domains[0]["domain"]

    if not prefix:
        prefix = f"user{int(time.time())}{random.randint(100,999)}"
    if not password:
        password = f"Pass{int(time.time())}{random.randint(1000,9999)}!"

    email = f"{prefix}@{domain}"

    # Try to create account with retry on 429
    max_retries = 5
    for attempt in range(max_retries):
        resp = requests.post(
            f"{MAILTM_BASE}/accounts",
            json={"address": email, "password": password}
        )
        if resp.status_code == 429:
            wait = (2 ** attempt) + random.random()
            time.sleep(wait)
            continue
        break
    else:
        raise Exception("Too many requests to Mail.tm – try again later.")

    if resp.status_code == 422:
        # If already taken, retry with random suffix
        prefix = f"user{int(time.time())}{random.randint(1000,9999)}"
        email = f"{prefix}@{domain}"
        resp = requests.post(
            f"{MAILTM_BASE}/accounts",
            json={"address": email, "password": password}
        )
        resp.raise_for_status()
    else:
        resp.raise_for_status()
    account = resp.json()

    # Login to get token
    resp = requests.post(
        f"{MAILTM_BASE}/token",
        json={"address": email, "password": password}
    )
    resp.raise_for_status()
    token = resp.json()["token"]

    return {
        "email": email,
        "password": password,
        "token": token,
        "account_id": account["id"]
    }

def wait_for_builder_verification(token, timeout=120, log_callback=None):
    """Poll Mail.tm for a verification email from help@builder.io.
       Returns the verification URL or None if not found.
    """
    headers = {"Authorization": f"Bearer {token}"}
    start = time.time()
    if log_callback:
        log_callback("Waiting for Builder verification email...")

    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{MAILTM_BASE}/messages", headers=headers)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            if log_callback:
                log_callback(f"Polling error: {e}")
            time.sleep(3)
            continue

        messages = resp.json()["hydra:member"]
        for msg in messages:
            sender = msg["from"]["address"].lower()
            subject = msg["subject"].lower()

            if sender == "help@builder.io" and "verify" in subject:
                if log_callback:
                    log_callback("Verification email received!")
                # Get full message
                resp = requests.get(
                    f"{MAILTM_BASE}/messages/{msg['id']}",
                    headers=headers
                )
                resp.raise_for_status()
                full = resp.json()
                text = full.get("text", "")
                # Extract verification URL
                match = re.search(
                    r'https://builder\.io/__/auth/action\?[^\s<>"\']+',
                    text
                )
                if match:
                    return match.group(0)
                else:
                    if log_callback:
                        log_callback("Warning: verification email found but URL missing")
                    return None
        time.sleep(3)

    if log_callback:
        log_callback("Timeout. Verification email not received.")
    return None

# ---------- Firebase verification via OOB code ----------
def verify_email_with_oob(oob_code, api_key):
    """
    Directly call Firebase setAccountInfo API to verify email.
    Include all headers from the HAR file to avoid 403.
    """
    url = f"https://www.googleapis.com/identitytoolkit/v3/relyingparty/setAccountInfo?key={api_key}"
    payload = {"oobCode": oob_code}
    headers = {
        "Content-Type": "application/json",
        "Origin": "https://builder.io",
        "Referer": "https://builder.io/",
        "X-Client-Version": "Firefox/JsCore/3.7.5/FirebaseCore-web",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:155.0) Gecko/20100101 Firefox/155.0",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    resp = requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    return resp.json()

# ---------- Firebase functions ----------
def firebase_signup(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_API_KEY}"
    payload = {
        "returnSecureToken": True,
        "email": email,
        "password": password,
        "clientType": "CLIENT_TYPE_WEB"
    }
    resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
    resp.raise_for_status()
    data = resp.json()
    return data["idToken"], data["localId"], data["email"]

def send_verification_email(id_token):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={FIREBASE_API_KEY}"
    payload = {"requestType": "VERIFY_EMAIL", "idToken": id_token}
    headers = {"Content-Type": "application/json"}
    resp = requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    return resp.json()

def lookup_account(id_token):
    """Get account info including emailVerified status."""
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={FIREBASE_API_KEY}"
    payload = {"idToken": id_token}
    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    users = data.get("users", [])
    if users:
        return users[0]
    return None

# ---------- Builder signup payload ----------
SIGNUP_TEMPLATE = """{
  "organization": {
    "id": "__ORG_ID__",
    "createdDate": __TIMESTAMP__,
    "meta": {},
    "name": "__EMAIL__",
    "customTargetingAttributes": {},
    "smartTargetingAttributes": {},
    "customTrackingEvents": [],
    "coreContentEntries": [],
    "siteUrl": "",
    "defaultQuery": [],
    "themeCss": "",
    "emailThemeCss": "",
    "subscription": "",
    "inactive": false,
    "referrer": "https://www.builder.io/",
    "useHTags": true,
    "integrationVerified": false,
    "views": [],
    "roles": [
      {"id":"reviewer","name":"Reviewer","description":"View only role","globalFilters":{},"options":{"read":true,"viewOnly":true,"create":false,"publish":false,"editCode":false,"editDesigns":false,"admin":false,"editLayouts":false,"editLayers":false,"editContentPriority":false,"editFolders":false,"editAiInstructions":false,"editProjects":false,"modifyMcpServers":false,"modifyWorkflowIntegrations":false,"modifyProjectSettings":false,"connectCodeRepository":false,"createProjects":false,"indexDesignSystems":false,"sendPullRequests":true,"mergePullRequests":false},"models":"all","projects":"all","environment":{"pushAllowedOrgIds":[],"sync":true,"canPushToAllOrgs":true},"locales":{"allowedLocalesEditList":[],"canEditAllLocales":true}},
      {"id":"contributor","name":"Contributor","description":"Can edit basic fields (e.g. text, images), but can't add, remove, or move blocks","globalFilters":{},"options":{"read":true,"viewOnly":false,"create":true,"publish":true,"editCode":false,"editDesigns":false,"admin":false,"editLayouts":false,"editLayers":false,"editContentPriority":true,"editFolders":false,"editProjects":false,"modifyMcpServers":false,"modifyWorkflowIntegrations":false,"modifyProjectSettings":false,"connectCodeRepository":false,"createProjects":false,"indexDesignSystems":false,"sendPullRequests":true,"mergePullRequests":false},"models":"all","projects":"all","environment":{"pushAllowedOrgIds":[],"sync":true,"canPushToAllOrgs":true},"locales":{"allowedLocalesEditList":[],"canEditAllLocales":true}},
      {"id":"editor","name":"Editor","description":"Can edit content (e.g. add, remove, edit blocks), but can't edit designs or styling","globalFilters":{},"options":{"read":true,"viewOnly":false,"create":true,"publish":true,"editCode":false,"editDesigns":false,"admin":false,"editLayouts":true,"editLayers":false,"editContentPriority":true,"editFolders":true,"editProjects":false,"modifyMcpServers":false,"modifyWorkflowIntegrations":false,"modifyProjectSettings":false,"connectCodeRepository":false,"createProjects":false,"indexDesignSystems":false,"sendPullRequests":true,"mergePullRequests":false},"models":"all","projects":"all","environment":{"pushAllowedOrgIds":[],"sync":true,"canPushToAllOrgs":true},"locales":{"allowedLocalesEditList":[],"canEditAllLocales":true}},
      {"id":"creator","name":"Designer","description":"Can create and edit content and designs","globalFilters":{},"options":{"read":true,"viewOnly":false,"create":true,"publish":true,"editCode":false,"editDesigns":true,"admin":false,"editLayouts":true,"editLayers":true,"editContentPriority":true,"editFolders":true,"editProjects":false,"modifyMcpServers":false,"modifyWorkflowIntegrations":false,"modifyProjectSettings":false,"connectCodeRepository":false,"createProjects":true,"indexDesignSystems":false,"sendPullRequests":true,"mergePullRequests":false,"fusionHostingPublish":true},"models":"all","projects":"all","environment":{"pushAllowedOrgIds":[],"sync":true,"canPushToAllOrgs":true},"locales":{"allowedLocalesEditList":[],"canEditAllLocales":true}},
      {"id":"developer","name":"Developer","description":"Can create and edit content, designs, code, and models","globalFilters":{},"options":{"read":true,"viewOnly":false,"create":true,"publish":true,"editCode":true,"editDesigns":true,"admin":false,"editLayouts":true,"editLayers":true,"editContentPriority":true,"editFolders":true,"editProjects":true,"modifyMcpServers":true,"modifyWorkflowIntegrations":true,"modifyProjectSettings":true,"connectCodeRepository":true,"createProjects":true,"indexDesignSystems":true,"sendPullRequests":true,"mergePullRequests":true,"fusionHostingPublish":true,"fusionHostingRevokeAiToken":true},"models":"all","projects":"all","environment":{"pushAllowedOrgIds":[],"sync":true,"canPushToAllOrgs":true},"locales":{"allowedLocalesEditList":[],"canEditAllLocales":true}},
      {"id":"admin","name":"Admin","description":"Can do everything including managing users and payment","globalFilters":{},"options":{"read":true,"viewOnly":false,"create":true,"publish":true,"editCode":true,"editDesigns":true,"admin":true,"editLayouts":true,"editLayers":true,"editContentPriority":true,"editFolders":true,"editProjects":true,"modifyMcpServers":true,"modifyWorkflowIntegrations":true,"modifyProjectSettings":true,"connectCodeRepository":true,"createProjects":true,"indexDesignSystems":true,"sendPullRequests":true,"mergePullRequests":true,"fusionHostingPublish":true,"fusionHostingRevokeAiToken":true},"models":"all","projects":"all","environment":{"pushAllowedOrgIds":[],"sync":true,"canPushToAllOrgs":true},"locales":{"allowedLocalesEditList":[],"canEditAllLocales":true}}
    ],
    "fonts": {"allowGoogleFonts":true,"customFonts":[]},
    "subscriptionSettings": "",
    "@version": 9,
    "loadPlugins": [],
    "webhooks": [],
    "workflows": [],
    "publishRules": [],
    "parentOrganization": "",
    "hasIntegrated": "none",
    "intent": "integrate",
    "ecommerceBackend": "none",
    "type": "root",
    "kind": "hybrid",
    "settings": {
      "statisticalSignificance": false,
      "reloadPreviewOnUrlPathTargetChange": true,
      "reloadPreviewForMobile": false,
      "showSitePreviewTab": false,
      "shopify": false,
      "shopifyPlan": "",
      "shopifyStoreName": "",
      "shopifyStoreDomain": "",
      "shopifyStorePasscode": "",
      "shopifySafeMode": true,
      "shopifyUseProxySiteApiDirectly": false,
      "shopifyUseRenderTag": false,
      "useProxy": false,
      "shopifyAutoPublishMetaTagsToTheme": true,
      "shopifyFullThemeEditing": true,
      "showCoreContent": false,
      "proxyPreview": false,
      "ssoProviderId": "",
      "ssoRestrictedMode": false,
      "ssoDefaultRole": "",
      "defaultRole": "",
      "ssoDefaultSpace": "",
      "publicSpaceJoin": {"enabled":false,"defaultRole":"developer"},
      "showTemplatesOnPageCreate": false,
      "showBlocksFieldType": false,
      "allowImagesInRichText": false,
      "showInlineTextEditOption": true,
      "richTextPasteWithFormatting": false,
      "enableModelValidationHooks": false,
      "enableOrgInsights": false,
      "allowMultipleUrls": false,
      "allowMembersOfOrgToJoinSpaces": false,
      "allowMembersOfOrgToJoinThisSpace": true,
      "allowLegacyPlanSubscriptions": false,
      "editorShowShopifyBlocks": false,
      "editorEnableEditingUrlLogic": true,
      "editorOnlyUseInheritedFonts": false,
      "strictValidateReactNative": false,
      "defaultPDFPaperSize": "",
      "targetsReactNative": false,
      "usePatchUpdates": false,
      "useDebouncedEdits": false,
      "debounceTextEdits": false,
      "useNewPublishUi": false,
      "hideGetStartedContentList": false,
      "hideDarkMode": false,
      "hideLinkUrlInputField": false,
      "showImageSizesInput": false,
      "componentsOnlyMode": false,
      "aiContentTraining": false,
      "aiVisualEditorEnabledForEnterprise": true,
      "allowBuiltInComponents": true,
      "allowImportFromWeb": false,
      "allowMarginEditing": true,
      "useDefaultStyles": true,
      "useDefaultMargins": true,
      "allowShopifyThemeEditing": false,
      "hideShopifyThemeEditor": false,
      "hideLocale": false,
      "allowOverridingLocales": false,
      "showContentListLocalePicker": false,
      "showApiModelNameMismatchErrorDialog": true,
      "useCurrentLocaleForRequiredLocalizedFields": false,
      "disableAutoProvisioningSSO": false,
      "showLocaleIntegrationErrorDialog": true,
      "prettifyStateVariableNames": true,
      "optimizeContentVisibility": false,
      "enableBuilderHosting": false,
      "templateFolders": [],
      "symbolFolders": [],
      "mediaFolders": [],
      "absoluteMode": true,
      "aiFeatures": true,
      "controlModelAvailability": false,
      "allowedAiModels": [],
      "autoModelOverride": "",
      "llmGatewayEnabled": true,
      "disableFusionHosting": false,
      "smartTargeting": "disabled",
      "governance": "new-content-only",
      "allowShopifyHighSpeedMode": false,
      "allowPublishUnpublishByBuilderAdmin": true,
      "plugins": {},
      "swatchColors": ["#D0021B","#F5A623","#F8E71C","#8B572A","#7ED321","#417505","#BD10E0","#9013FE","#4A90E2","#50E3C2","#B8E986","#000000","#4A4A4A","#9B9B9B","#FFFFFF"],
      "onlyAllowSwatchColors": false,
      "partytownPlugin": {},
      "apps": {},
      "overrideSubscription": {},
      "companySize": "",
      "integrationTypes": [],
      "otherIntegrationTypes": "",
      "techStack": [],
      "attribution": [],
      "attributionComment": "",
      "otherTechStack": "",
      "visualEditorAiCustomInstructions": "",
      "visualEditorAiStyleInspirationURL": "",
      "skipBranchPrompt": false,
      "integrations": {"instagram":{"username":"","dateTokenLastRefreshed":0,"accessToken":"","externalUserId":""},"appetize":{"key":""}},
      "origins": {"qa":"","dev":"","production":""},
      "customComponents": [],
      "customHtmlAttributes": [],
      "enforceMaxUsers": false,
      "triggerContentWebhookOnSpaceOrEnvironmentUpdates": false,
      "triggerGlobalWebhooksOnContentRepublish": false,
      "userPluginIntegrationsRequested": [],
      "isUserPluginIntegrationRequestGranted": false,
      "customPrompt": "",
      "codeStylePrompt": "",
      "requireAllSpacesToBeAssociatedToTeams": false,
      "enableEnvironmentLiveSync": true,
      "editWebhooksAndValidationHooksPerEnvironment": false,
      "allowHeadersForGetRequests": false,
      "enabledGitProviders": {"github":true,"selfHostedGithub":false,"gitlab":true,"azure":true,"bitbucket":true},
      "githubEnterpriseSetupValue": null,
      "gitlabEnterpriseSetupValue": null,
      "gitlabEnterprisePAT": null,
      "gitlabEnterpriseMode": "oauth",
      "gitlabGroupId": "",
      "gitlabCloudFallbackToken": null,
      "azureCloudFallbackToken": null,
      "bitbucketCloudFallbackToken": null,
      "bitbucketEnterprisePAT": null,
      "builtInStarterTemplateSettings": {
        "fusion-starter": {"isDefault":true,"isVisible":true},
        "angular-tailwind-vite-starter": {"isDefault":false,"isVisible":true},
        "svelte-tailwind-vite-starter": {"isDefault":false,"isVisible":true},
        "vue-tailwind-vite-starter": {"isDefault":false,"isVisible":true},
        "agent-native-starter": {"isDefault":false,"isVisible":true}
      },
      "useLocalDocker": false,
      "useTempFolderForFusion": false,
      "canUseCustomLocal": false,
      "previewPasswordProtection": {"enabled":false,"password":""},
      "enforceDesktopAppOnly": false,
      "runInPty": false,
      "overrideDevToolsVersion": "",
      "autoDetectDevServerPatterns": [],
      "environmentVariables": [],
      "defaultProjectVisibility": "public",
      "certIgnorePattern": "",
      "enableDataEncryption": false,
      "enableNativeAppDevelopment": false,
      "useBinaryDistributions": false,
      "disableNoCrawlHeader": false,
      "omitHiddenLayers": false,
      "restrictPublicApiKeyIncludeUnpublished": false,
      "privacyMode": {"enabled":false,"mcpServers":false,"redactUserMessages":false,"redactLLMMessages":false},
      "hideBuiltInMcpServers": false,
      "projectsUseGithubServerToken": false,
      "prAuthoringMode": "",
      "fusionPrLabel": "",
      "defaultCommitMode": "prs",
      "disableFigmaImageUpload": false,
      "showPreviewUrlTemplate": false,
      "enforceCustomComponentValidation": false,
      "enforceCustomComponentSubfieldValidation": false,
      "maxAgentIterations": 0,
      "defaultBackgroundAgentModel": "",
      "defaultBackgroundAgentEffort": "",
      "maxAgentCompletions": 250,
      "enableTicketAssessment": false,
      "ticketAssessmentPrompt": "",
      "ticketAssessmentModel": "",
      "ticketAssessmentDailyLimit": 0,
      "prReviewer": {},
      "fusionWebhooks": [],
      "enforceUserLimit": false,
      "defaultUserCreditLimit": 0,
      "defaultUserCreditLimitType": "flexible",
      "enrichEditorPreviewRefs": true
    },
    "flags": {"optimizeImages": false},
    "payment": {"lastDigits":"","expires":{}},
    "lastUpdateBy": "__USER_ID__",
    "originalAuthProvider": "email",
    "hasCompletedGettingStartedChecklist": false,
    "hasImportedFromFigma": false,
    "hasIntegratedFigma": false,
    "hasMadeSomethingInteractive": false,
    "onboardingStepsCompleted": [],
    "fusionReferralsSeen": [],
    "fusionReferrals": ""
  },
  "organization_private": {
    "events": [
      {
        "type": "signup",
        "href": "https://builder.io/signup",
        "parsedShopifyInfo": {
          "shopifyHmacDetails": {},
          "referrer": "https://www.builder.io/",
          "useGoogle": false,
          "useGithub": false
        }
      }
    ]
  },
  "userSettings": {
    "ownerId": "__USER_ID__",
    "createdDate": __TIMESTAMP__,
    "id": "__USER_ID__",
    "emailVerified": false,
    "signupDate": __TIMESTAMP__,
    "invitedDate": null,
    "organizations": [],
    "email": "__EMAIL__",
    "hasTemplates": false,
    "views": [],
    "roles": {},
    "jobFunctions": [],
    "jobFunction": "",
    "userType": "",
    "companySize": "",
    "otherJobFunction": "",
    "techStack": [],
    "otherTechStack": "",
    "useCases": [],
    "useCase": "",
    "spaceKind": "hybrid",
    "attribution": [],
    "otherUseCase": "",
    "intent": "",
    "intentSelect": [],
    "otherIntentSelect": "",
    "onboardingStepsCompleted": [],
    "hasCompletedOnboarding": false,
    "hasCompletedGettingStartedChecklist": false,
    "hasImportedFromFigma": false,
    "hasIntegratedFigma": false,
    "hasMadeSomethingInteractive": false,
    "isChecklistDismissed": false,
    "hasSeenTutorialSprig": false,
    "name": "__EMAIL__",
    "authProvider": "email",
    "unsubscribed": false,
    "referrer": "https://www.builder.io/",
    "photoURL": "",
    "isTemplateTester": false,
    "experiments": {},
    "organization": "",
    "role": "",
    "permissionsLevel": "",
    "apps": {"collective":{"agentId":"","agentRole":""}},
    "turnOffCommentNotifications": false,
    "turnOffReviewNotifications": false,
    "autoOpenDesktopApp": false,
    "showDesktopAppPromo": false,
    "hasSeenQualityReviewWizard": false,
    "meta": {"firstPublish": null},
    "githubAccessToken": "",
    "githubAppAccessToken": "",
    "ghesGithubAppAccessToken": "",
    "gitlabAppAccessToken": "",
    "gitlabAppRefreshToken": "",
    "gitlabAppTokenExpiresAt": null,
    "azureDevOpsOrganization": "",
    "bitbucketConnected": false,
    "githubUsername": "",
    "ghesGithubUsername": "",
    "gitlabUsername": "",
    "bitbucketUsername": "",
    "azureDevOpsUsername": "",
    "githubEmailAddresses": [],
    "privacyMode": {}
  }
}"""

def build_signup_payload(email, user_id, org_id):
    timestamp = int(time.time() * 1000)
    payload_str = SIGNUP_TEMPLATE
    payload_str = payload_str.replace("__ORG_ID__", org_id)
    payload_str = payload_str.replace("__USER_ID__", user_id)
    payload_str = payload_str.replace("__EMAIL__", email)
    payload_str = payload_str.replace("__TIMESTAMP__", str(timestamp))
    return json.loads(payload_str)

# ---------- Streaming generator ----------
def signup_generator(prefix=None, password=None, count=1):
    total = int(count)
    if total < 1:
        yield f"data: {json.dumps({'type': 'error', 'message': 'Count must be at least 1'})}\n\n"
        return

    successful = 0
    created_accounts = []

    for i in range(total):
        index = i + 1
        yield f"data: {json.dumps({'type': 'log', 'message': f'🔨 Creating account {index}/{total} ...'})}\n\n"

        try:
            # 1. Create temporary email
            yield f"data: {json.dumps({'type': 'log', 'message': f'📧 Account {index}: Creating temporary email...'})}\n\n"
            mail = create_mail(prefix, password)
            email = mail["email"]
            pwd = mail["password"]
            mail_token = mail["token"]
            yield f"data: {json.dumps({'type': 'log', 'message': f'✅ Account {index}: Email created: {email}'})}\n\n"

            # 2. Firebase signup
            yield f"data: {json.dumps({'type': 'log', 'message': f'🔥 Account {index}: Firebase signup...'})}\n\n"
            id_token, local_id, _ = firebase_signup(email, pwd)
            yield f"data: {json.dumps({'type': 'log', 'message': f'✅ Account {index}: Firebase success.'})}\n\n"

            # 3. Send verification email
            yield f"data: {json.dumps({'type': 'log', 'message': f'📨 Account {index}: Sending verification email...'})}\n\n"
            try:
                send_verification_email(id_token)
                yield f"data: {json.dumps({'type': 'log', 'message': f'✅ Account {index}: Verification email sent.'})}\n\n"
                verification_sent = True
            except Exception as e:
                verification_sent = False
                yield f"data: {json.dumps({'type': 'log', 'message': f'⚠️ Account {index}: Failed to send verification: {e}'})}\n\n"

            # 4. Wait for verification email and verify via API
            verified = False
            if verification_sent:
                yield f"data: {json.dumps({'type': 'log', 'message': f'⏳ Account {index}: Waiting for verification email...'})}\n\n"
                verify_url = wait_for_builder_verification(mail_token, timeout=120, log_callback=None)
                if verify_url:
                    yield f"data: {json.dumps({'type': 'log', 'message': f'🔗 Account {index}: Verification URL found.'})}\n\n"
                    parsed = urllib.parse.urlparse(verify_url)
                    query_params = urllib.parse.parse_qs(parsed.query)
                    oob_code = query_params.get('oobCode', [None])[0]
                    api_key = query_params.get('apiKey', [None])[0]
                    if oob_code and api_key:
                        try:
                            yield f"data: {json.dumps({'type': 'log', 'message': f'🔐 Account {index}: Calling Firebase verification API...'})}\n\n"
                            verify_email_with_oob(oob_code, api_key)
                            yield f"data: {json.dumps({'type': 'log', 'message': f'✅ Account {index}: Verification API call succeeded.'})}\n\n"
                            time.sleep(3)
                            yield f"data: {json.dumps({'type': 'log', 'message': f'🔍 Account {index}: Checking email verification status...'})}\n\n"
                            user_info = lookup_account(id_token)
                            if user_info and user_info.get('emailVerified', False):
                                verified = True
                                yield f"data: {json.dumps({'type': 'log', 'message': f'✅ Account {index}: Email verified successfully!'})}\n\n"
                            else:
                                yield f"data: {json.dumps({'type': 'log', 'message': f'⚠️ Account {index}: Email not verified after API call.'})}\n\n"
                        except Exception as e:
                            yield f"data: {json.dumps({'type': 'log', 'message': f'⚠️ Account {index}: Error during verification API: {e}'})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'log', 'message': f'⚠️ Account {index}: Could not extract oobCode or apiKey from URL.'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'log', 'message': f'⏰ Account {index}: Timeout waiting for verification email.'})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'log', 'message': f'⚠️ Account {index}: Skipping verification because email not sent.'})}\n\n"

            # 5. Builder.io signup
            yield f"data: {json.dumps({'type': 'log', 'message': f'🏗️ Account {index}: Creating Builder.org...'})}\n\n"
            org_id = str(uuid.uuid4()).replace("-", "")
            payload = build_signup_payload(email, local_id, org_id)
            headers = HEADERS.copy()
            headers["Authorization"] = f"Bearer {id_token}"

            resp = requests.post(SIGNUP_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            yield f"data: {json.dumps({'type': 'log', 'message': f'✅ Account {index}: Builder signup successful!'})}\n\n"

            # Save account
            if save_account(email, pwd):
                successful += 1
                created_accounts.append({"email": email, "password": pwd})
                yield f"data: {json.dumps({'type': 'log', 'message': f'💾 Account {index}: Saved to accounts.txt'})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'log', 'message': f'⚠️ Account {index}: Failed to save account'})}\n\n"

        except Exception as e:
            error_msg = str(e)
            if hasattr(e, 'response') and e.response:
                error_msg += f"\nResponse: {e.response.text}"
            yield f"data: {json.dumps({'type': 'error', 'message': f'❌ Account {index} failed: {error_msg}'})}\n\n"

        if i < total - 1:
            time.sleep(3 + random.random() * 2)

    yield f"data: {json.dumps({'type': 'log', 'message': f'🏁 Bulk creation finished. {successful}/{total} accounts created successfully.'})}\n\n"
    yield f"event: accounts_created\ndata: {json.dumps(created_accounts)}\n\n"

# ---------- Flask routes ----------
app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/signup_stream", methods=["POST"])
def signup_stream():
    prefix = request.form.get("prefix", "").strip()
    password = request.form.get("password", "").strip()
    count = request.form.get("count", 1)
    try:
        count = int(count)
    except:
        count = 1
    if count < 1:
        count = 1
    if count > 50:
        count = 50

    return Response(
        stream_with_context(signup_generator(prefix, password, count)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )

@app.route("/get_accounts", methods=["GET"])
def get_accounts():
    filename = "accounts.txt"
    accounts = []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and "," in line:
                    email, pwd = line.split(",", 1)
                    accounts.append({"email": email, "password": pwd})
    except FileNotFoundError:
        pass
    return jsonify(accounts)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
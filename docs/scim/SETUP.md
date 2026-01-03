# SCIM 2.0 Provisioning Setup Guide

This guide covers setting up SCIM 2.0 provisioning with your Identity Provider (IdP).

## Overview

SCIM (System for Cross-domain Identity Management) enables automatic user and group provisioning from your IdP to the portal. When users are added or removed in your IdP, the changes are automatically synchronized.

## Prerequisites

- Admin access to the portal
- Admin access to your IdP (Okta, Azure AD, etc.)
- SCIM 2.0 support in your IdP

## Step 1: Create a SCIM Token

1. Log in to the portal as an admin
2. Navigate to **Settings → Provisioning**
3. Click **+ Create Token**
4. Enter a descriptive name (e.g., "Okta Production")
5. Optionally set an expiration (recommended: 365 days)
6. Click **Create**
7. **Important**: Copy the token immediately - it won't be shown again

```
Token format: scim_<random_string>
Example: scim_a1b2c3d4e5f6g7h8i9j0...
```

## Step 2: Configure Your IdP

### Okta Setup

1. In Okta Admin Console, go to **Applications → Applications**
2. Click **Create App Integration**
3. Select **SCIM 2.0**
4. Configure the SCIM connection:
   - **SCIM connector base URL**: `https://your-portal.example.com/scim/v2`
   - **Unique identifier field**: `userName`
   - **Authentication mode**: HTTP Header
   - **Authorization**: Bearer Token
   - **Bearer Token**: Paste your SCIM token

5. Test the connection

### Azure AD (Entra ID) Setup

1. In Azure Portal, go to **Enterprise Applications**
2. Click **New Application → Create your own application**
3. Select **Integrate any other application**
4. Go to **Provisioning → Get started**
5. Set **Provisioning Mode** to **Automatic**
6. Configure Admin Credentials:
   - **Tenant URL**: `https://your-portal.example.com/scim/v2`
   - **Secret Token**: Paste your SCIM token
7. Click **Test Connection**
8. Configure attribute mappings

### OneLogin Setup

1. In OneLogin Admin, go to **Applications → Add App**
2. Search for "SCIM Provisioner"
3. Configure the connection:
   - **SCIM Base URL**: `https://your-portal.example.com/scim/v2`
   - **SCIM Bearer Token**: Paste your SCIM token
4. Enable provisioning

## Step 3: Configure Attribute Mappings

Ensure these attributes are mapped:

| IdP Attribute | SCIM Attribute | Required |
|---------------|----------------|----------|
| Email | emails[primary eq true].value | Yes |
| Username | userName | Yes |
| First Name | name.givenName | No |
| Last Name | name.familyName | No |
| Display Name | displayName | No |
| Active | active | Yes |

## Step 4: Configure Group Provisioning

### In Your IdP

1. Enable "Push Groups" feature
2. Select groups to provision
3. Configure group membership sync

### In the Portal

1. Go to **Settings → Provisioning → Mappings**
2. Click **+ Add Mapping**
3. Select the SCIM group
4. Select the target project
5. Choose the role (viewer/editor/admin)
6. Click **Create**

The portal will automatically:
- Add group members to the project with the specified role
- Remove members when they're removed from the group
- Preserve any manually-added project memberships

## Step 5: Test the Integration

1. **User Provisioning Test**:
   - Add a test user to a provisioned group in your IdP
   - Verify the user appears in the portal within 1-5 minutes
   - Verify project access

2. **Deprovision Test**:
   - Remove the test user from the group
   - Verify project access is revoked
   - Verify user sessions are invalidated

3. **Full Sync Test**:
   - In the portal, click **Sync Now**
   - Verify all memberships are current

## Troubleshooting

### "Authentication Failed" Error

- Verify the SCIM token is correct and not expired
- Ensure the token hasn't been revoked
- Check that you're using "Bearer" authentication

### Users Not Syncing

- Check that "Push Users" is enabled in your IdP
- Verify attribute mappings are correct
- Check the SCIM token permissions

### Groups Not Appearing

- Enable "Push Groups" in your IdP
- Create group → project mappings in the portal
- Trigger a manual sync

### Permission Issues

- Verify the group mapping has the correct role
- Check that the mapping is enabled
- Ensure the target project exists

## Security Best Practices

1. **Rotate tokens regularly** (every 90-365 days)
2. **Use separate tokens** for production and test environments
3. **Monitor token usage** via the Provisioning panel
4. **Enable audit logging** for provisioning events
5. **Review mappings** periodically

## Support

For issues with SCIM provisioning:
1. Check the [Runbooks](./RUNBOOKS.md) for common issues
2. Review [Security Guide](./SECURITY.md) for security concerns
3. Contact support with SCIM request logs

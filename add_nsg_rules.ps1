# Run these commands in PowerShell (as admin) to open ports in Azure NSG
# Prereqs: Azure CLI installed (https://aka.ms/InstallAzureCLIDeb) and logged in: az login

# Configuration - matches your Pulumi defaults
$resourceGroup = "rg-voice-agent"
$nsgName = "nsg-voice"  # Pulumi auto-generates from "nsg" resource name

# Login if not already
# az login

# Add port 3000 (Frontend) - missing from Pulumi!
az network nsg rule create `
  --resource-group $resourceGroup `
  --nsg-name $nsgName `
  --name "frontend-3000" `
  --priority 130 `
  --direction Inbound `
  --access Allow `
  --protocol Tcp `
  --source-port-range "*" `
  --destination-port-range "3000" `
  --source-address-prefix "*" `
  --destination-address-prefix "*"

# Verify all rules
az network nsg rule list --resource-group $resourceGroup --nsg-name $nsgName -o table

# Optional: Also ensure 8080 rule exists (voice-ws)
az network nsg rule create `
  --resource-group $resourceGroup `
  --nsg-name $nsgName `
  --name "voice-ws-8080" `
  --priority 120 `
  --direction Inbound `
  --access Allow `
  --protocol Tcp `
  --source-port-range "*" `
  --destination-port-range "8080" `
  --source-address-prefix "*" `
  --destination-address-prefix "*" `
  --output none 2>$null || Write-Host "Rule may already exist"

Write-Host "NSG rules updated. Test: http://85.211.177.112:3000 and http://85.211.177.112:8080/health"
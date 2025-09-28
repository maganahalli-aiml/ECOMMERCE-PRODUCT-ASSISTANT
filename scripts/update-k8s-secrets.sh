#!/bin/bash

# Script to update Kubernetes secrets for product-assistant
# Usage: ./scripts/update-k8s-secrets.sh

set -e

echo "🔧 Updating Kubernetes secrets for product-assistant..."

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "❌ kubectl is not installed or not in PATH"
    exit 1
fi

# Check if we can connect to the cluster
if ! kubectl get nodes &> /dev/null; then
    echo "❌ Cannot connect to Kubernetes cluster"
    echo "💡 Make sure you've run: aws eks update-kubeconfig --name product-assistant-cluster --region us-east-1"
    exit 1
fi

echo "✅ Connected to Kubernetes cluster"

# Delete existing secret if it exists
echo "🗑️  Deleting existing secret (if exists)..."
kubectl delete secret product-assistant-secrets --ignore-not-found=true

# Create new secret (you'll need to set these environment variables)
echo "🔐 Creating new secret..."

# Check if required environment variables are set
if [[ -z "$GROQ_API_KEY" || -z "$ASTRA_DB_API_ENDPOINT" || -z "$ASTRA_DB_APPLICATION_TOKEN" || -z "$ASTRA_DB_KEYSPACE" ]]; then
    echo "❌ Required environment variables are not set:"
    echo "   - GROQ_API_KEY"
    echo "   - ASTRA_DB_API_ENDPOINT"
    echo "   - ASTRA_DB_APPLICATION_TOKEN"
    echo "   - ASTRA_DB_KEYSPACE"
    echo ""
    echo "💡 Set them and run this script again:"
    echo "   export GROQ_API_KEY='your-groq-key'"
    echo "   export ASTRA_DB_API_ENDPOINT='your-astra-endpoint'"
    echo "   export ASTRA_DB_APPLICATION_TOKEN='your-astra-token'"
    echo "   export ASTRA_DB_KEYSPACE='your-keyspace'"
    echo "   ./scripts/update-k8s-secrets.sh"
    exit 1
fi

kubectl create secret generic product-assistant-secrets \
    --from-literal=GROQ_API_KEY="${GROQ_API_KEY}" \
    --from-literal=ASTRA_DB_API_ENDPOINT="${ASTRA_DB_API_ENDPOINT}" \
    --from-literal=ASTRA_DB_APPLICATION_TOKEN="${ASTRA_DB_APPLICATION_TOKEN}" \
    --from-literal=ASTRA_DB_KEYSPACE="${ASTRA_DB_KEYSPACE}"

echo "✅ Kubernetes secret 'product-assistant-secrets' created successfully!"

# Verify the secret was created
echo "🔍 Verifying secret..."
kubectl get secret product-assistant-secrets -o jsonpath='{.data}' | jq 'keys'

echo "🎉 Secret update completed!"
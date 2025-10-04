#!/bin/bash

# Quick AWS Resource Termination Script
# This script immediately stops/terminates EC2, EKS, and ES resources

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REGION="us-east-1"

echo -e "${RED}⚠️  DANGER: This will TERMINATE all EC2, EKS, and ES resources! ⚠️${NC}"
echo -e "${YELLOW}Type 'DELETE' to confirm:${NC}"
read -r confirmation

if [[ $confirmation != "DELETE" ]]; then
    echo -e "${YELLOW}Termination cancelled.${NC}"
    exit 0
fi

echo -e "${BLUE}Starting immediate resource termination...${NC}"

# Function to terminate all EC2 instances
terminate_all_ec2() {
    echo -e "${BLUE}=== Terminating ALL EC2 Instances ===${NC}"
    
    # Get all instances (running, stopped, stopping)
    INSTANCE_IDS=$(aws ec2 describe-instances --region $REGION \
        --filters "Name=instance-state-name,Values=running,stopped,stopping,pending" \
        --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null)
    
    if [ ! -z "$INSTANCE_IDS" ] && [ "$INSTANCE_IDS" != "None" ]; then
        echo -e "${YELLOW}Found instances: $INSTANCE_IDS${NC}"
        echo -e "${RED}Terminating ALL instances...${NC}"
        aws ec2 terminate-instances --instance-ids $INSTANCE_IDS --region $REGION
        echo -e "${GREEN}✓ Termination initiated for all EC2 instances${NC}"
    else
        echo -e "${GREEN}No EC2 instances found${NC}"
    fi
}

# Function to delete all EKS clusters
delete_all_eks() {
    echo -e "${BLUE}=== Deleting ALL EKS Clusters ===${NC}"
    
    # Get all clusters
    CLUSTERS=$(aws eks list-clusters --region $REGION --query 'clusters[]' --output text 2>/dev/null)
    
    for cluster in $CLUSTERS; do
        if [ ! -z "$cluster" ]; then
            echo -e "${YELLOW}Processing EKS cluster: $cluster${NC}"
            
            # Delete node groups first
            NODE_GROUPS=$(aws eks list-nodegroups --cluster-name $cluster --region $REGION --query 'nodegroups[]' --output text 2>/dev/null)
            
            for nodegroup in $NODE_GROUPS; do
                if [ ! -z "$nodegroup" ]; then
                    echo -e "${YELLOW}Deleting node group: $nodegroup${NC}"
                    aws eks delete-nodegroup --cluster-name $cluster --nodegroup-name $nodegroup --region $REGION
                fi
            done
            
            # Delete the cluster
            echo -e "${RED}Deleting EKS cluster: $cluster${NC}"
            aws eks delete-cluster --name $cluster --region $REGION
            echo -e "${GREEN}✓ Deletion initiated for cluster: $cluster${NC}"
        fi
    done
    
    if [ -z "$CLUSTERS" ]; then
        echo -e "${GREEN}No EKS clusters found${NC}"
    fi
}

# Function to delete Elasticsearch domains
delete_all_elasticsearch() {
    echo -e "${BLUE}=== Deleting ALL Elasticsearch Domains ===${NC}"
    
    # Get all ES domains
    ES_DOMAINS=$(aws es list-domain-names --region $REGION --query 'DomainNames[].DomainName' --output text 2>/dev/null)
    
    for domain in $ES_DOMAINS; do
        if [ ! -z "$domain" ]; then
            echo -e "${RED}Deleting ES domain: $domain${NC}"
            aws es delete-elasticsearch-domain --domain-name $domain --region $REGION
            echo -e "${GREEN}✓ Deletion initiated for ES domain: $domain${NC}"
        fi
    done
    
    if [ -z "$ES_DOMAINS" ]; then
        echo -e "${GREEN}No Elasticsearch domains found${NC}"
    fi
}

# Function to delete OpenSearch domains (newer version of ES)
delete_all_opensearch() {
    echo -e "${BLUE}=== Deleting ALL OpenSearch Domains ===${NC}"
    
    # Get all OpenSearch domains
    OS_DOMAINS=$(aws opensearch list-domain-names --region $REGION --query 'DomainNames[].DomainName' --output text 2>/dev/null)
    
    for domain in $OS_DOMAINS; do
        if [ ! -z "$domain" ]; then
            echo -e "${RED}Deleting OpenSearch domain: $domain${NC}"
            aws opensearch delete-domain --domain-name $domain --region $REGION
            echo -e "${GREEN}✓ Deletion initiated for OpenSearch domain: $domain${NC}"
        fi
    done
    
    if [ -z "$OS_DOMAINS" ]; then
        echo -e "${GREEN}No OpenSearch domains found${NC}"
    fi
}

# Function to stop all running instances immediately
stop_all_ec2() {
    echo -e "${BLUE}=== Stopping ALL Running EC2 Instances ===${NC}"
    
    # Get only running instances
    RUNNING_INSTANCES=$(aws ec2 describe-instances --region $REGION \
        --filters "Name=instance-state-name,Values=running" \
        --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null)
    
    if [ ! -z "$RUNNING_INSTANCES" ] && [ "$RUNNING_INSTANCES" != "None" ]; then
        echo -e "${YELLOW}Stopping running instances: $RUNNING_INSTANCES${NC}"
        aws ec2 stop-instances --instance-ids $RUNNING_INSTANCES --region $REGION
        echo -e "${GREEN}✓ Stop initiated for running instances${NC}"
    else
        echo -e "${GREEN}No running EC2 instances found${NC}"
    fi
}

# Function to delete Auto Scaling Groups
delete_auto_scaling_groups() {
    echo -e "${BLUE}=== Deleting Auto Scaling Groups ===${NC}"
    
    ASG_NAMES=$(aws autoscaling describe-auto-scaling-groups --region $REGION --query 'AutoScalingGroups[].AutoScalingGroupName' --output text 2>/dev/null)
    
    for asg in $ASG_NAMES; do
        if [ ! -z "$asg" ]; then
            echo -e "${YELLOW}Updating ASG to 0 instances: $asg${NC}"
            aws autoscaling update-auto-scaling-group --auto-scaling-group-name $asg --min-size 0 --max-size 0 --desired-capacity 0 --region $REGION
            
            echo -e "${RED}Deleting ASG: $asg${NC}"
            aws autoscaling delete-auto-scaling-group --auto-scaling-group-name $asg --force-delete --region $REGION
            echo -e "${GREEN}✓ ASG deletion initiated: $asg${NC}"
        fi
    done
    
    if [ -z "$ASG_NAMES" ]; then
        echo -e "${GREEN}No Auto Scaling Groups found${NC}"
    fi
}

# Main execution with menu
main() {
    echo -e "${BLUE}AWS Resource Termination Menu${NC}"
    echo -e "${YELLOW}1. Stop all running EC2 instances (keeps instances for later)${NC}"
    echo -e "${RED}2. TERMINATE all EC2 instances (PERMANENT DELETION)${NC}"
    echo -e "${RED}3. Delete all EKS clusters${NC}"
    echo -e "${RED}4. Delete all Elasticsearch/OpenSearch domains${NC}"
    echo -e "${RED}5. Delete Auto Scaling Groups${NC}"
    echo -e "${RED}6. NUCLEAR OPTION - DELETE EVERYTHING${NC}"
    echo -e "${YELLOW}0. Exit${NC}"
    echo ""
    echo -e "${YELLOW}Choose option (0-6):${NC}"
    read -r choice
    
    case $choice in
        1)
            stop_all_ec2
            ;;
        2)
            terminate_all_ec2
            ;;
        3)
            delete_all_eks
            ;;
        4)
            delete_all_elasticsearch
            delete_all_opensearch
            ;;
        5)
            delete_auto_scaling_groups
            ;;
        6)
            echo -e "${RED}NUCLEAR OPTION: Deleting ALL resources!${NC}"
            delete_auto_scaling_groups
            terminate_all_ec2
            delete_all_eks
            delete_all_elasticsearch
            delete_all_opensearch
            ;;
        0)
            echo -e "${GREEN}Exited safely${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid option${NC}"
            exit 1
            ;;
    esac
    
    echo -e "${GREEN}=== Operation Complete ===${NC}"
    echo -e "${YELLOW}Note: Resources may take a few minutes to fully terminate${NC}"
    echo -e "${YELLOW}Check AWS Console to verify deletions${NC}"
}

# Check AWS CLI
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}Error: AWS CLI not configured${NC}"
    exit 1
fi

# Run main function
main
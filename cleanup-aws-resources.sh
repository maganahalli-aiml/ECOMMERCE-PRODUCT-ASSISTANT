#!/bin/bash

# AWS Resource Cleanup Script
# This script will delete all EKS, ECR, EC2, and related resources to avoid charges

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
CLUSTER_NAME="product-assistant-cluster"
ECR_REPO_NAME="product-assistant"
STACK_NAME="product-assistant-stack"
REGION="us-east-1"

echo -e "${BLUE}Starting AWS Resource Cleanup...${NC}"
echo -e "${YELLOW}This will DELETE all resources and cannot be undone!${NC}"
echo -e "${RED}Are you sure you want to continue? (yes/no)${NC}"
read -r confirmation

if [[ $confirmation != "yes" ]]; then
    echo -e "${YELLOW}Cleanup cancelled.${NC}"
    exit 0
fi

# Function to check if AWS CLI is configured
check_aws_cli() {
    if ! aws sts get-caller-identity &> /dev/null; then
        echo -e "${RED}Error: AWS CLI not configured or no valid credentials found${NC}"
        exit 1
    fi
    echo -e "${GREEN}AWS CLI configured successfully${NC}"
}

# Function to delete EKS cluster
delete_eks_cluster() {
    echo -e "${BLUE}=== Deleting EKS Cluster ===${NC}"
    
    # Check if cluster exists
    if aws eks describe-cluster --name $CLUSTER_NAME --region $REGION &> /dev/null; then
        echo -e "${YELLOW}Found EKS cluster: $CLUSTER_NAME${NC}"
        
        # Delete node groups first
        echo -e "${YELLOW}Deleting node groups...${NC}"
        NODE_GROUPS=$(aws eks list-nodegroups --cluster-name $CLUSTER_NAME --region $REGION --query 'nodegroups[]' --output text 2>/dev/null || echo "")
        
        for nodegroup in $NODE_GROUPS; do
            if [ ! -z "$nodegroup" ]; then
                echo -e "${YELLOW}Deleting node group: $nodegroup${NC}"
                aws eks delete-nodegroup --cluster-name $CLUSTER_NAME --nodegroup-name $nodegroup --region $REGION
                
                echo -e "${YELLOW}Waiting for node group $nodegroup to be deleted...${NC}"
                aws eks wait nodegroup-deleted --cluster-name $CLUSTER_NAME --nodegroup-name $nodegroup --region $REGION
                echo -e "${GREEN}Node group $nodegroup deleted${NC}"
            fi
        done
        
        # Delete the cluster
        echo -e "${YELLOW}Deleting EKS cluster: $CLUSTER_NAME${NC}"
        aws eks delete-cluster --name $CLUSTER_NAME --region $REGION
        
        echo -e "${YELLOW}Waiting for cluster to be deleted (this may take 10-15 minutes)...${NC}"
        aws eks wait cluster-deleted --name $CLUSTER_NAME --region $REGION
        echo -e "${GREEN}EKS cluster deleted successfully${NC}"
    else
        echo -e "${YELLOW}No EKS cluster found with name: $CLUSTER_NAME${NC}"
    fi
}

# Function to delete ECR repository
delete_ecr_repository() {
    echo -e "${BLUE}=== Deleting ECR Repository ===${NC}"
    
    if aws ecr describe-repositories --repository-names $ECR_REPO_NAME --region $REGION &> /dev/null; then
        echo -e "${YELLOW}Found ECR repository: $ECR_REPO_NAME${NC}"
        
        # Delete all images first
        echo -e "${YELLOW}Deleting all images in repository...${NC}"
        aws ecr batch-delete-image --repository-name $ECR_REPO_NAME --region $REGION \
            --image-ids "$(aws ecr list-images --repository-name $ECR_REPO_NAME --region $REGION --query 'imageIds[]' --output json)" \
            2>/dev/null || echo "No images to delete"
        
        # Delete the repository
        echo -e "${YELLOW}Deleting ECR repository: $ECR_REPO_NAME${NC}"
        aws ecr delete-repository --repository-name $ECR_REPO_NAME --region $REGION --force
        echo -e "${GREEN}ECR repository deleted successfully${NC}"
    else
        echo -e "${YELLOW}No ECR repository found with name: $ECR_REPO_NAME${NC}"
    fi
}

# Function to terminate all EC2 instances
terminate_ec2_instances() {
    echo -e "${BLUE}=== Terminating EC2 Instances ===${NC}"
    
    # Get all running instances
    INSTANCE_IDS=$(aws ec2 describe-instances --region $REGION \
        --filters "Name=instance-state-name,Values=running,stopped,stopping" \
        --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null || echo "")
    
    if [ ! -z "$INSTANCE_IDS" ]; then
        echo -e "${YELLOW}Found EC2 instances: $INSTANCE_IDS${NC}"
        echo -e "${YELLOW}Terminating all EC2 instances...${NC}"
        aws ec2 terminate-instances --instance-ids $INSTANCE_IDS --region $REGION
        
        echo -e "${YELLOW}Waiting for instances to terminate...${NC}"
        aws ec2 wait instance-terminated --instance-ids $INSTANCE_IDS --region $REGION
        echo -e "${GREEN}All EC2 instances terminated${NC}"
    else
        echo -e "${YELLOW}No EC2 instances found to terminate${NC}"
    fi
}

# Function to delete CloudFormation stack
delete_cloudformation_stack() {
    echo -e "${BLUE}=== Deleting CloudFormation Stack ===${NC}"
    
    if aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION &> /dev/null; then
        echo -e "${YELLOW}Found CloudFormation stack: $STACK_NAME${NC}"
        
        # Delete any pending change sets first
        CHANGE_SETS=$(aws cloudformation list-change-sets --stack-name $STACK_NAME --region $REGION --query 'Summaries[].ChangeSetName' --output text 2>/dev/null || echo "")
        for changeset in $CHANGE_SETS; do
            if [ ! -z "$changeset" ]; then
                echo -e "${YELLOW}Deleting change set: $changeset${NC}"
                aws cloudformation delete-change-set --stack-name $STACK_NAME --change-set-name $changeset --region $REGION
            fi
        done
        
        echo -e "${YELLOW}Deleting CloudFormation stack: $STACK_NAME${NC}"
        aws cloudformation delete-stack --stack-name $STACK_NAME --region $REGION
        
        echo -e "${YELLOW}Waiting for stack to be deleted...${NC}"
        aws cloudformation wait stack-delete-complete --stack-name $STACK_NAME --region $REGION
        echo -e "${GREEN}CloudFormation stack deleted successfully${NC}"
    else
        echo -e "${YELLOW}No CloudFormation stack found with name: $STACK_NAME${NC}"
    fi
}

# Function to delete VPC and related resources (if not managed by CloudFormation)
cleanup_vpc_resources() {
    echo -e "${BLUE}=== Cleaning up VPC Resources ===${NC}"
    
    # Find VPC with EKS tag
    VPC_ID=$(aws ec2 describe-vpcs --region $REGION --filters "Name=tag:Name,Values=EKS-VPC" --query 'Vpcs[0].VpcId' --output text 2>/dev/null || echo "None")
    
    if [ "$VPC_ID" != "None" ] && [ ! -z "$VPC_ID" ]; then
        echo -e "${YELLOW}Found VPC: $VPC_ID${NC}"
        
        # Delete NAT Gateways
        NAT_GATEWAYS=$(aws ec2 describe-nat-gateways --region $REGION --filter "Name=vpc-id,Values=$VPC_ID" --query 'NatGateways[].NatGatewayId' --output text 2>/dev/null || echo "")
        for nat_gw in $NAT_GATEWAYS; do
            if [ ! -z "$nat_gw" ]; then
                echo -e "${YELLOW}Deleting NAT Gateway: $nat_gw${NC}"
                aws ec2 delete-nat-gateway --nat-gateway-id $nat_gw --region $REGION
            fi
        done
        
        # Release Elastic IPs
        ELASTIC_IPS=$(aws ec2 describe-addresses --region $REGION --query 'Addresses[].AllocationId' --output text 2>/dev/null || echo "")
        for eip in $ELASTIC_IPS; do
            if [ ! -z "$eip" ]; then
                echo -e "${YELLOW}Releasing Elastic IP: $eip${NC}"
                aws ec2 release-address --allocation-id $eip --region $REGION 2>/dev/null || echo "Could not release $eip"
            fi
        done
        
        echo -e "${GREEN}VPC cleanup initiated${NC}"
    else
        echo -e "${YELLOW}No EKS VPC found${NC}"
    fi
}

# Function to delete Load Balancers
delete_load_balancers() {
    echo -e "${BLUE}=== Deleting Load Balancers ===${NC}"
    
    # Delete Application Load Balancers
    ALB_ARNS=$(aws elbv2 describe-load-balancers --region $REGION --query 'LoadBalancers[].LoadBalancerArn' --output text 2>/dev/null || echo "")
    for alb_arn in $ALB_ARNS; do
        if [ ! -z "$alb_arn" ]; then
            echo -e "${YELLOW}Deleting ALB: $alb_arn${NC}"
            aws elbv2 delete-load-balancer --load-balancer-arn $alb_arn --region $REGION
        fi
    done
    
    # Delete Classic Load Balancers
    CLB_NAMES=$(aws elb describe-load-balancers --region $REGION --query 'LoadBalancerDescriptions[].LoadBalancerName' --output text 2>/dev/null || echo "")
    for clb_name in $CLB_NAMES; do
        if [ ! -z "$clb_name" ]; then
            echo -e "${YELLOW}Deleting CLB: $clb_name${NC}"
            aws elb delete-load-balancer --load-balancer-name $clb_name --region $REGION
        fi
    done
}

# Main execution
main() {
    echo -e "${BLUE}Starting cleanup process...${NC}"
    
    check_aws_cli
    
    echo -e "${YELLOW}Cleanup will be performed in this order:${NC}"
    echo -e "${YELLOW}1. Delete CloudFormation stack (includes most resources)${NC}"
    echo -e "${YELLOW}2. Delete EKS cluster (if not in stack)${NC}"
    echo -e "${YELLOW}3. Delete ECR repository${NC}"
    echo -e "${YELLOW}4. Terminate EC2 instances${NC}"
    echo -e "${YELLOW}5. Delete Load Balancers${NC}"
    echo -e "${YELLOW}6. Cleanup VPC resources${NC}"
    echo ""
    
    # Try CloudFormation first (most comprehensive)
    delete_cloudformation_stack
    
    # Individual resource cleanup (in case CloudFormation doesn't handle everything)
    delete_eks_cluster
    delete_ecr_repository
    terminate_ec2_instances
    delete_load_balancers
    cleanup_vpc_resources
    
    echo -e "${GREEN}=== Cleanup Complete ===${NC}"
    echo -e "${GREEN}All AWS resources have been deleted or scheduled for deletion.${NC}"
    echo -e "${YELLOW}Note: Some resources (like NAT Gateways) may take a few minutes to fully terminate.${NC}"
    echo -e "${YELLOW}Please check your AWS console to verify all resources are deleted.${NC}"
}

# Run the main function
main
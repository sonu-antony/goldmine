variable "region" {
  description = "AWS region."
  type        = string
  default     = "eu-central-1"
}

variable "name" {
  description = "Name prefix for everything created here."
  type        = string
  default     = "goldmine"
}

variable "vpc_id" {
  description = "VPC the cluster lives in."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnets for the cluster subnet group (at least two availability zones)."
  type        = list(string)
}

variable "allowed_cidr_blocks" {
  description = "Networks that may connect on port 5439: the VPN or the Airbyte and Dagster hosts. Never 0.0.0.0/0."
  type        = list(string)
}

variable "node_type" {
  description = "RA3 separates compute from storage, so you pay for storage you use and can resize compute alone."
  type        = string
  default     = "ra3.xlplus"
}

variable "number_of_nodes" {
  description = "Compute nodes. A few hundred gigabytes fits comfortably on two ra3.xlplus nodes."
  type        = number
  default     = 2
}

variable "pause_outside_business_hours" {
  description = "Pause the cluster at night and at the weekend. Right for a development cluster, wrong for production."
  type        = bool
  default     = false
}

variable "concurrency_scaling_limit_minutes" {
  description = "Monthly cap on concurrency scaling, which is billed per second beyond the free credits."
  type        = number
  default     = 120
}

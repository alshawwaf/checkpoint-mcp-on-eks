variable "region" {
  description = "AWS region for the build resources."
  type        = string
  default     = "us-east-1"
}

variable "prefix" {
  description = "Optional short prefix to run a second, independent stack in the same account."
  type        = string
  default     = ""

  validation {
    condition     = can(regex("^([a-z][a-z0-9-]{0,11})?$", var.prefix))
    error_message = "The prefix must match [a-z][a-z0-9-]{0,11}, or be empty."
  }
}

variable "extra_tags" {
  description = "Additional tags applied to every resource."
  type        = map(string)
  default     = {}
}

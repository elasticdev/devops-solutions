class Main(newSchedStack):

    def __init__(self,stackargs):

        newSchedStack.__init__(self,stackargs)

        # Add default variables
        self.parse.add_required(key="ci_environment")
        self.parse.add_required(key="parent_id",default="null")
        self.parse.add_required(key="visibility_level",default="public")

        self.parse.add_required(key="runner_docker_image",default="alpine")
        self.parse.add_required(key="runner_concurrent",default="4")
        self.parse.add_required(key="spot_price",default="0.004")
        self.parse.add_required(key="vpc_id")
        self.parse.add_required(key="subnet_ids")
        self.parse.add_required(key="sg_id")
        self.parse.add_required(key="bastion_sg_id",default="null")
        self.parse.add_required(key="instance_type",default="t3.micro") 
        self.parse.add_required(key="disksize",default="20") 

        self.parse.add_required(key="gitlab_runners_token_hash")
        #self.parse.add_required(key="gitlab_runners_ami",default="ami-0d75513e7706cf2d9")  # ubuntu 22.04 lts eu-west-1
        #self.parse.add_required(key="gitlab_runners_ami",default="ami-0f93e856d36a101f8")  # ubuntu 20.04 lts eu-west-1
        self.parse.add_required(key="gitlab_runners_ami",default="ami-0f03fd8a6e34800c0") # ubuntu 18.04 lts
        self.parse.add_required(key="gitlab_runner_aws_access_key")
        self.parse.add_required(key="gitlab_runner_aws_secret_key")

        self.parse.add_optional(key="gitlab_runner_autoscaling_hash",default="null")

        self.parse.add_optional(key="suffix_id",default="null")
        self.parse.add_optional(key="suffix_length",default="4")  

        self.parse.add_optional(key="aws_default_region",default="us-west-1")
        self.parse.add_required(key="aws_zone",default="a")
        self.parse.add_optional(key="cloud_tags_hash",default="null")
        self.parse.add_optional(key="bucket_acl",default="private")

        # Add substack
        self.stack.add_substack('elasticdev:::gitlab_subgroup')
        self.stack.add_substack('elasticdev:::aws_s3_bucket')
        self.stack.add_substack('elasticdev:::new_ec2_ssh_key')
        self.stack.add_substack('elasticdev:::aws_iam')
        self.stack.add_substack('elasticdev:::ec2_ubuntu_admin')

        self.stack.init_substacks()

    def _get_cache_config(self):
    
        s3_bucket = self._get_bucket_name()

        s3 = { "ServerAddress": "s3.amazonaws.com",
               "AccessKey": self.stack.gitlab_runner_aws_access_key,
               "SecretKey": self.stack.gitlab_runner_aws_secret_key,
               "BucketName": s3_bucket,
               "BucketLocation": self.stack.aws_default_region
               }
    
        cache = { "Type": "s3",
                  "Shared": True,
                  "s3": s3
                  }
    
        return cache
    
    def _get_machine_options(self):
    
        MachineOptions = [ "amazonec2-access-key={}".format(self.stack.gitlab_runner_aws_access_key),
                           "amazonec2-secret-key={}".format(self.stack.gitlab_runner_aws_secret_key),
                           "amazonec2-region={}".format(self.stack.aws_default_region),
                           "amazonec2-vpc-id={}".format(self.stack.vpc_id),
                           "amazonec2-subnet-id={}".format(self.stack.subnet_id),
                           "amazonec2-zone={}".format(self.stack.aws_zone),
                           "amazonec2-use-private-address=true",
                           "amazonec2-tags=gitlab-runner-autoscaler,gitlab,group-runner,{}".format(self.stack.ci_environment),
                           "amazonec2-security-group={}".format(self.stack.sg_id.split("sg-")[1]),
                           "amazonec2-instance-type={}".format(self.stack.instance_type),
                           "amazonec2-request-spot-instance=true",
                           "amazonec2-spot-price={}".format(self.stack.spot_price)
                           ]

        if self.stack.gitlab_runners_ami: 
            MachineOptions.append("amazonec2-ami={}".format(self.stack.gitlab_runners_ami))
    
        machine = { "MachineDriver": "amazonec2",
                    "MachineName": "gitlab-ci-machine-%s",
                    "OffPeakTimezone": "",
                    "OffPeakIdleCount": 0,
                    "OffPeakIdleTime": 0,
                    "IdleCount": 0,
                    "MachineOptions": MachineOptions
                    }
    
        return machine
    
    def _get_autoscaling(self):
    
        autoscaling = None
    
        if self.stack.gitlab_runner_autoscaling_hash:
            try:
                autoscaling = self.stack.b64_decode(self.stack.gitlab_runner_autoscaling_hash)
            except:
                autoscaling = None
    
        if autoscaling: return autoscaling
    
        autoscaling = [ { "Periods": [ "* * 1-23 * * mon-sun *"],
                          "IdleCount": 1,
                          "IdleTime": 60,
                          "Timezone": "UTC"
                          }
                        ]
    
        return autoscaling
    
    def _get_gitlab_runner_toml(self):
        
        import toml
    
        runner = { "name": "gitlab-runner-autoscaler",
                   "url": "https://gitlab.com/",
                   "token": self.stack.b64_decode(self.stack.gitlab_runners_token_hash),
                   "executor": "docker+machine",
                   "limit": 4,
                   "docker": { "tls_verify": False,
                               "image": self.stack.runner_docker_image,
                               "privileged": True,
                               "disable_cache": True,
                               "shm_size": 0
                               },
                   "cache": self._get_cache_config(),
                   "machine": self._get_machine_options(),
                   }
    
        autoscaling = self._get_autoscaling()
    
        if autoscaling: runner["autoscaling"] = autoscaling
    
        values = { "concurrent": int(self.stack.runner_concurrent),
                   "check_interval": 0,
                   "runners": [ runner ]
                   }
    
        with open(self.stack.gitlab_runner_config_file,"w") as _f:
            toml.dump(values,_f )
    
        toml_str_b64 = self.stack.b64_encode(open(self.stack.gitlab_runner_config_file,"r").read())
    
        return toml_str_b64.strip()
    
    def _get_user_data(self):

        import os
    
        self.stack.set_variable("gitlab_runner_config_file",os.path.join("/tmp",self.stack.random_id()))

        toml_str_b64 = self._get_gitlab_runner_toml()
    
        contents = '''#!/bin/bash
apt-get update
apt install apt-transport-https ca-certificates curl gnupg-agent software-properties-common -y
apt install docker.io docker-compose -y

curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"

base=https://github.com/docker/machine/releases/download/v0.16.0 &&
curl -L $base/docker-machine-$(uname -s)-$(uname -m) >/tmp/docker-machine &&
sudo mv /tmp/docker-machine /usr/local/bin/docker-machine &&
chmod +x /usr/local/bin/docker-machine

curl -L https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh | sudo bash
apt-get install gitlab-runner -y 

gitlab-runner restart

sleep 5 

#gitlab-runner register \
#          --non-interactive \
#          --executor "docker+machine" \
#          --docker-image {} \
#          --url "https://gitlab.com/" \
#          --registration-token "{}" \
#          --maintenance-note "Free-form maintainer notes about this runner" \
#          --locked="false" \
#          --access-level="not_protected"

gitlab-runner restart

sleep 5 

mkdir -p /etc/gitlab-runner
echo "{}" | base64 -d > /etc/gitlab-runner/config.toml

sleep 5 

gitlab-runner restart

        '''.format(self.stack.runner_docker_image,
                   self.stack.b64_decode(self.stack.gitlab_runners_token_hash),
                   toml_str_b64)
    
        user_data = contents + "\n"
    
        #return self.stack.b64_encode(user_data.encode('utf-8')).decode('ascii')

        return user_data

    def run_runner_manager(self):

        self.stack.init_variables()

        self.stack.set_variable("subnet_id",self.stack.subnet_ids.split(",")[0])
        self.stack.set_variable("hostname","gitlab-runner-manager-admin")

        if not self.stack.bastion_sg_id:
            self.stack.set_variable("bastion_sg_id",self.sg_id)

        user_data_hash = self.stack.b64_encode(self._get_user_data())

        overide_values = { "hostname":self.stack.hostname,
                           "ip_key": "public_ip",
                           "user_data_hash": user_data_hash,
                           "ssh_key_name": self._get_ssh_key_name() }
                           #"spot": None,

        default_values = { "vpc_id":self.stack.vpc_id,
                           "subnet_ids":self.stack.subnet_ids,
                           "instance_type": self.stack.instance_type,
                           "disksize": self.stack.disksize,
                           "aws_default_region":self.stack.aws_default_region,
                           "sg_id":self.stack.bastion_sg_id,
                           }

        inputargs = {"default_values":default_values,
                     "overide_values":overide_values}

        inputargs["automation_phase"] = "infrastructure"
        inputargs["human_description"] = 'Create EC2 {}'.format(self.stack.hostname)

        return self.stack.ec2_ubuntu_admin.insert(display=True,**inputargs)

    def _get_policy_hash(self):

        s3_bucket = self._get_bucket_name()

        policy = { "Version": "2012-10-17",
                   "Statement": [ { "Effect": "Allow",
                                    "Action": "ec2:*",
                                              "Resource": "*"
                                    },
                                  { "Effect": "Allow",
                                    "Action": [ "s3:*" ],
                                    "Resource": [ "arn:aws:s3:::{}".format(s3_bucket), 
                                                  "arn:aws:s3:::{}/*".format(s3_bucket) ]
                                    }
                                  ]
                   }

        return self.stack.b64_encode(policy)

    def _get_gitlab_group_name(self):

        suffix_id = self._determine_suffix_id()
        return "{}-{}".format(self.stack.ci_environment,suffix_id)

    def _determine_suffix_id(self):

        if self.stack.suffix_id: return str(self.stack.suffix_id).lower()

        return self.stack.b64_encode(self.stack.ci_environment)[0:int(self.stack.suffix_length)].lower()

    def _set_cloud_tag_hash(self):

        try:
            cloud_tags = self.stack.b64_decode(self.stack.cloud_tags_hash)
        except:
            cloud_tags = {}

        cloud_tags["ci_environment"] = self.stack.ci_environment
        cloud_tags["aws_default_region"] = self.stack.aws_default_region

        return self.stack.b64_encode(cloud_tags)

    def _get_bucket_name(self):

        suffix_id = self._determine_suffix_id()

        # cache shared bucket
        s3_bucket = "gitlab-runner-{}-{}".format(self.stack.ci_environment,suffix_id)

        return s3_bucket

    def _get_ssh_key_name(self):

        return "{}-key".format(self.stack.ci_environment) 

    def run_sshkey(self):

        self.stack.init_variables()

        ssh_key_name = self._get_ssh_key_name()

        overide_values = { "key_name":ssh_key_name }
        default_values = { "aws_default_region":self.stack.aws_default_region }

        inputargs = {"default_values":default_values,
                     "overide_values":overide_values}
    
        inputargs["automation_phase"] = "infrastructure"
        inputargs["human_description"] = 'Create and upload ssh key name {}'.format(ssh_key_name)
    
        return self.stack.new_ec2_ssh_key.insert(display=True,**inputargs)

    def run_iam(self):

        self.stack.init_variables()

        policy_hash = self._get_policy_hash()

        name = "gitlab-{}-iam".format(self.stack.ci_environment)

        overide_values = { "policy_hash":policy_hash,
                           "iam_name": name,
                           "policy_name": name
                           }

        default_values = { "aws_default_region":self.stack.aws_default_region }

        inputargs = {"default_values":default_values,
                     "overide_values":overide_values}
    
        inputargs["automation_phase"] = "infrastructure"
        inputargs["human_description"] = 'Create IAM role for {}'.format(self.stack.ci_environment)
    
        return self.stack.aws_iam.insert(display=True,**inputargs)

    def run_s3(self):

        self.stack.init_variables()
        self.stack.set_parallel()

        cloud_tags_hash = self._set_cloud_tag_hash()
        s3_bucket = self._get_bucket_name()

        default_values = { "aws_default_region":self.stack.aws_default_region }

        overide_values = { "bucket": s3_bucket,
                           "acl": self.stack.bucket_acl,
                           "cloud_tags_hash":cloud_tags_hash,
                           "force_destroy": "true" }

        inputargs = { "default_values":default_values,
                      "overide_values":overide_values }
    
        inputargs["automation_phase"] = "infrastructure"
        inputargs["human_description"] = 'Create s3 bucket {}'.format(s3_bucket)
    
        return self.stack.aws_s3_bucket.insert(display=True,**inputargs)

    def run_subgroup(self):

        self.stack.init_variables()

        default_values = {}

        overide_values = { "group_name": self._get_gitlab_group_name(),
                           "visibility_level":self.stack.visibility_level }

        inputargs = { "default_values":default_values,
                      "overide_values":overide_values }

        inputargs["automation_phase"] = "infrastructure"
        inputargs["human_description"] = 'Add subgroup {}'.format(overide_values["group_name"])
    
        return self.stack.gitlab_subgroup.insert(display=True,**inputargs)

    def run(self):
    
        self.stack.unset_parallel()
        #self.add_job("sshkey")
        #self.add_job("s3")
        #self.add_job("iam")
        #self.add_job("subgroup")
        self.add_job("runner_manager")

        return self.finalize_jobs()

    def schedule(self):

        #sched = self.new_schedule()
        #sched.job = "subgroup"
        #sched.archive.timeout = 1800
        #sched.archive.timewait = 120
        #sched.conditions.retries = 1 
        #sched.automation_phase = "infrastructure"
        #sched.human_description = 'Create Gitlab subgroup'
        #sched.on_success = [ "s3" ]
        #self.add_schedule()

        #sched = self.new_schedule()
        #sched.job = "s3"
        #sched.archive.timeout = 1200
        #sched.archive.timewait = 120
        #sched.automation_phase = "infrastructure"
        #sched.human_description = "Create s3 buckets"
        #sched.on_success = [ "iam" ]
        #self.add_schedule()

        #sched = self.new_schedule()
        #sched.job = "iam"
        #sched.archive.timeout = 1800
        #sched.archive.timewait = 120
        #sched.automation_phase = "infrastructure"
        #sched.human_description = "Create IAM credentials"
        #sched.on_success = [ "sshkey" ]
        #self.add_schedule()

        #sched = self.new_schedule()
        #sched.job = "sshkey"
        #sched.archive.timeout = 1200
        #sched.archive.timewait = 120
        #sched.automation_phase = "infrastructure"
        #sched.on_success = [ "runner_manager" ]
        #sched.human_description = "Upload user public ssh key"
        #self.add_schedule()

        sched = self.new_schedule()
        sched.job = "runner_manager"
        sched.archive.timeout = 1200
        sched.archive.timewait = 120
        sched.conditions.retries = 1 
        sched.automation_phase = "infrastructure"
        sched.human_description = "Create gitlab manager vm"
        self.add_schedule()

        return self.get_schedules()

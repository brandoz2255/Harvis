#!/usr/bin/env python3
import os
import yaml
import questionary


def ask_basic_info():
    app_name = questionary.text("📝 Application name:").ask()
    docker_image = questionary.text("🐳 Docker image (e.g. nginx:alpine):").ask()
    container_port = questionary.text("📦 Container port", default="80").ask()
    return app_name, docker_image, int(container_port)


def ask_replicas_and_namespace():
    replicas = questionary.text("🔁 Number of replicas", default="1").ask()
    namespace = questionary.text("📂 Kubernetes namespace", default="default").ask()
    return int(replicas), namespace


def ask_service():
    svc_type = questionary.select(
        "🏷️ Service type", choices=["ClusterIP", "NodePort", "LoadBalancer"]
    ).ask()
    svc_port = questionary.text("🔌 Service port", default="80").ask()
    return svc_type, int(svc_port)


def ask_secrets():
    if not questionary.confirm("Generate a Secret?").ask():
        return None, []

    secret_data = {}
    env_from_secrets = []

    while questionary.confirm("   Add Secret entry?").ask():
        key = questionary.text("      🔑 Secret Key:").ask()
        value = questionary.text("      🔐 Secret Value:").ask()
        secret_data[key] = value

        if questionary.confirm("      ↪️ Expose as env var in container?").ask():
            env_from_secrets.append(
                {
                    "name": key,
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": None,  # We'll fill this later
                            "key": key,
                        }
                    },
                }
            )
    return secret_data, env_from_secrets


def ask_env_and_labels():
    env = {}
    labels = {}
    while questionary.confirm("Add an environment variable?").ask():
        key = questionary.text("   🔑 Key:").ask()
        value = questionary.text("   📋 Value:").ask()
        env[key] = value
    while questionary.confirm("Add a label?").ask():
        key = questionary.text("   🏷️ Key:").ask()
        value = questionary.text("   📋 Value:").ask()
        labels[key] = value
    return env, labels


def ask_resources():
    limits = {}
    requests = {}
    if questionary.confirm("Configure resource limits/requests?").ask():
        while questionary.confirm("   Add a limit?").ask():
            resource = questionary.select(
                "      Resource", choices=["cpu", "memory"]
            ).ask()
            amount = questionary.text("      Limit amount (e.g. 200m, 256Mi):").ask()
            limits[resource] = amount
        while questionary.confirm("   Add a request?").ask():
            resource = questionary.select(
                "      Resource", choices=["cpu", "memory"]
            ).ask()
            amount = questionary.text("      Request amount (e.g. 100m, 128Mi):").ask()
            requests[resource] = amount
    resources = {}
    if limits:
        resources["limits"] = limits
    if requests:
        resources["requests"] = requests
    return resources or None


def ask_ingress():
    if not questionary.confirm("Generate an Ingress resource?").ask():
        return None
    host = questionary.text("🌐 Ingress host (e.g. example.com):").ask()
    path = questionary.text("🚧 Path (default /):", default="/").ask()
    return {"host": host, "path": path}


def ask_configmap():
    if not questionary.confirm("Generate a ConfigMap?").ask():
        return None
    data = {}
    while questionary.confirm("   Add ConfigMap entry?").ask():
        key = questionary.text("      Key:").ask()
        value = questionary.text("      Value:").ask()
        data[key] = value
    return data


def build_deployment(cfg):
    container = {
        "name": cfg["app_name"],
        "image": cfg["docker_image"],
        "ports": [{"containerPort": cfg["container_port"]}],
    }
    if cfg["env"]:
        container["env"] = [{"name": k, "value": v} for k, v in cfg["env"].items()]
    if cfg["secret_env"]:
        for secret in cfg["secret_env"]:
            secret["valueFrom"]["secretKeyRef"]["name"] = f"{cfg['app_name']}-secret"
        container.setdefault("env", []).extend(cfg["secret_env"])
    if cfg["resources"]:
        container["resources"] = cfg["resources"]

    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": cfg["app_name"],
            "namespace": cfg["namespace"],
            "labels": {"app": cfg["app_name"], **cfg["labels"]},
        },
        "spec": {
            "replicas": cfg["replicas"],
            "selector": {"matchLabels": {"app": cfg["app_name"]}},
            "template": {
                "metadata": {"labels": {"app": cfg["app_name"]}},
                "spec": {"containers": [container]},
            },
        },
    }


def build_secret_manifest(cfg):
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": f"{cfg['app_name']}-secret",
            "namespace": cfg["namespace"],
        },
        "type": "Opaque",
        "stringData": cfg["secret_data"],
    }


def build_service(cfg):
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": f"{cfg['app_name']}-svc", "namespace": cfg["namespace"]},
        "spec": {
            "type": cfg["service_type"],
            "selector": {"app": cfg["app_name"]},
            "ports": [
                {
                    "protocol": "TCP",
                    "port": cfg["service_port"],
                    "targetPort": cfg["container_port"],
                }
            ],
        },
    }


def build_ingress_manifest(cfg):
    annotations = {"nginx.ingress.kubernetes.io/rewrite-target": "/"}
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": f"{cfg['app_name']}-ing",
            "namespace": cfg["namespace"],
            "annotations": annotations,
        },
        "spec": {
            "rules": [
                {
                    "host": cfg["ingress"]["host"],
                    "http": {
                        "paths": [
                            {
                                "path": cfg["ingress"]["path"],
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {
                                        "name": f"{cfg['app_name']}-svc",
                                        "port": {"number": cfg["service_port"]},
                                    }
                                },
                            }
                        ]
                    },
                }
            ]
        },
    }


def build_configmap_manifest(cfg):
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": f"{cfg['app_name']}-cm", "namespace": cfg["namespace"]},
        "data": cfg["configmap"],
    }


def main():
    # Interactive step-by-step prompts
    app_name, docker_image, container_port = ask_basic_info()
    replicas, namespace = ask_replicas_and_namespace()
    service_type, service_port = ask_service()
    env, labels = ask_env_and_labels()
    resources = ask_resources()
    ingress = ask_ingress()
    configmap = ask_configmap()
    secret_data, secret_env = ask_secrets()

    cfg = {
        "app_name": app_name,
        "docker_image": docker_image,
        "container_port": container_port,
        "replicas": replicas,
        "namespace": namespace,
        "service_type": service_type,
        "service_port": service_port,
        "env": env,
        "labels": labels,
        "resources": resources,
        "ingress": ingress,
        "configmap": configmap,
        "secret_data": secret_data,
        "secret_env": secret_env,
    }

    manifests = [build_deployment(cfg), build_service(cfg)]
    if ingress:
        manifests.append(build_ingress_manifest(cfg))
    if configmap:
        manifests.append(build_configmap_manifest(cfg))
    if secret_data:
        manifests.append(build_secret_manifest(cfg))

    output_dir = questionary.text("📁 Output directory", default="/app/output").ask()
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{app_name}-k8s.yaml")
    with open(output_path, "w") as f:
        yaml.dump_all(manifests, f, sort_keys=False)

    print(f"\n✅ Manifest generated at: {output_path}")


if __name__ == "__main__":
    main()

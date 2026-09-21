import zenoh

def listener(sample):
    try:
        print(
            f"[RX] key={sample.key_expr} "
            f"payload={sample.payload.to_bytes()}"
        )
    except Exception as e:
        print(f"[ERR] {e}")

conf = zenoh.Config()
conf.insert_json5(
    "connect/endpoints",
    '["tcp/127.0.0.1:7447"]'
)

session = zenoh.open(conf)

print("Zenoh monitor started")
print("subscribing: **")

sub = session.declare_subscriber(
    "**",
    listener
)

try:
    input("Press Enter to stop...\n")
finally:
    sub.undeclare()
    session.close()

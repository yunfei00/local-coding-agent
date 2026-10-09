class DemoEngine {
public:
    int run() const { return 24; }
};

int phase24_native_entry() {
    DemoEngine engine;
    return engine.run();
}

package T {
    action def A {
        action yesPath;
        then done;
        first start;
        then decide;
          if yes then yesPath;
          else done;
    }
}

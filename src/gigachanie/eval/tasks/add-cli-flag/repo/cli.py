import sys


def main(argv):
    name = argv[1] if len(argv) > 1 else 'world'
    print(f'hello {name}')


if __name__ == '__main__':
    main(sys.argv)
